# NL2SQL 动态 Schema 管理指南

本指南说明如何在不改一行 Python 代码的前提下，让智能体通过自然语言查询业务数据库。

管理员只需通过 Schema Registry 登记数据域、表、字段和关联关系，发布后 NL2SQL 即可自动识别并生成 SQL 查询。

---

## 1. 整体架构

```
管理员（schema:admin）
   │  Bearer Token
   ▼
/admin/schema  Schema Registry（登记草稿）
   │
   ▼
publish（校验 → 版本 + 变更日志 → 置 active）
   │
   ▼
NL2SQL 查询链路
   ├─ SchemaCatalog  只读取已发布(published)元数据
   ├─ 意图路由 + LLM 生成 SQL
   ├─ SQL Guard       只读/全表 allowlist/租户校验
   └─ ReadonlySqlExecutor  用只读账号执行
```

### 两条数据库连接（职责分离）

| 用途 | 连接配置 | 数据库账号 | 权限 |
|---|---|---|---|
| Schema 元数据登记/发布 | `MYSQL_*` 或 `CHAT_MYSQL_*` | 管理账号 | 增删改元数据 |
| NL2SQL 业务查询执行 | `SQL_READONLY_*` | `nl2sql_readonly` | 仅 `SELECT` |

**关键约束**：发布 Schema ≠ 自动给数据库账号授权。业务表必须显式执行 `GRANT SELECT` 后，只读账号才能查询。

---

## 2. 前置准备

### 2.1 建表与种子数据

```bash
# 建系统表（含 schema 元数据表）
mysql -h <MYSQL_HOST> -P 3306 -u root -p <MYSQL_DB> < scripts/chat_schema.sql

# 插入测试租户/用户/角色，并把 schema:admin 绑到管理员
mysql -h <MYSQL_HOST> -P 3306 -u root -p <MYSQL_DB> < scripts/test_data.sql
```

### 2.2 环境变量（.env）

```dotenv
# 管理连接（Schema 元数据）
MYSQL_HOST=...
MYSQL_PORT=3306
MYSQL_DB=enterprise_agent
MYSQL_ROOT_PASSWORD=...

# 只读查询连接（NL2SQL 执行）
SQL_READONLY_HOST=...
SQL_READONLY_PORT=3306
SQL_READONLY_USER=nl2sql_readonly
SQL_READONLY_PASSWORD=...
SQL_READONLY_DB=enterprise_agent

# Chat 存储后端
CHAT_STORAGE=mysql
```

> 若希望 Schema 元数据落在独立数据库，可额外设置 `CHAT_MYSQL_HOST/PORT/USER/PASSWORD/DB` 覆盖 `MYSQL_*`。

### 2.3 启动服务

```bash
.venv/Scripts/python.exe -m uvicorn main:app --host 0.0.0.0 --port 8000
```

### 2.4 获取管理员 Token

```http
POST http://localhost:8000/auth/login
Content-Type: application/json

{
  "tenant_id": "tenant-test",
  "username": "<管理员用户名>",
  "password": "<密码>"
}
```

响应中的 `access_token` 用作后续所有 `/admin/schema` 请求的：

```text
Authorization: Bearer <access_token>
```

要求该用户拥有 `schema:admin` 权限（`test_data.sql` 已为 `user-test-001` 预绑 `role-schema-admin`）。

---

## 3. 一次完整的登记流程

以业务表 `orders` 为例。

### 3.1 创建数据域（草稿）

```http
POST /admin/schema/domains
Authorization: Bearer <token>
Content-Type: application/json

{
  "name": "orders",
  "description": "销售订单数据域",
  "keywords": ["订单", "orders", "销售额"]
}
```

- `name` 数据域名称（也会作为域名）
- `keywords` 用于 NL2SQL 的自然语言→数据域识别
- 成功后返回 `status: "draft"`（此时 NL2SQL 还读不到）

### 3.2 探测真实表结构

先看真实库有哪些可用的字段：

```http
POST /admin/schema/domains/orders/introspect
Authorization: Bearer <token>
Content-Type: application/json

{
  "tables": ["orders", "order_items"],
  "include_columns": true
}
```

返回 `INFORMATION_SCHEMA` 探测到的候选列（仅草稿，不自动开放）。

### 3.3 登记表

```http
POST /admin/schema/domains/orders/tables
Authorization: Bearer <token>
Content-Type: application/json

{
  "table": "orders",
  "description": "订单主表",
  "required_tenant_filter": true
}
```

- `required_tenant_filter: true` 强制所有查询必须带租户过滤条件

### 3.4 登记字段

```http
POST /admin/schema/domains/orders/columns
Authorization: Bearer <token>
Content-Type: application/json

{
  "table": "orders",
  "columns": [
    {"column_name": "order_id", "data_type": "varchar", "business_name": "订单号",
     "selectable": true, "filterable": true, "sortable": false, "aggregatable": false},
    {"column_name": "amount", "data_type": "decimal", "business_name": "订单金额",
     "selectable": true, "filterable": true, "sortable": true, "aggregatable": true},
    {"column_name": "customer_phone", "data_type": "varchar", "business_name": "客户电话",
     "selectable": false, "sensitive": true, "masking_rule": "mask_last4"}
  ]
}
```

字段能力标记：

| 标记 | 含义 |
|---|---|
| `selectable` | 可被 SELECT 输出 |
| `filterable` | 可出现在 WHERE 过滤 |
| `sortable` | 可排序 |
| `aggregatable` | 可参与聚合（SUM/COUNT/AVG） |
| `sensitive` | 敏感字段 |
| `masking_rule` | 脱敏规则 |

> 敏感字段默认不应 `selectable: true`；`tenant_id` 不得作为可暴露字段登记。

### 3.5 发布（写入版本）

```http
POST /admin/schema/domains/orders/publish
Authorization: Bearer <token>
Content-Type: application/json

{
  "version": 1,
  "comment": "首次发布订单域"
}
```

- `version` 可选，省略则自动递增
- 发布在一个事务内：校验真实表存在、至少一个可查询字段、敏感字段合规、JOIN 完整
- 生成 snapshot hash、写入 `sql_schema_versions`（published）与 `sql_schema_change_logs`
- 成功后 `status: "active"`，NL2SQL 立即可查

### 3.6 验证

```bash
curl http://localhost:8000/admin/schema/domains -H "Authorization: Bearer <token>"
```

---

## 4. 登记复杂 JOIN

JOIN 存于表元数据的 `allowed_joins`，发布时展开写入版本化的 `sql_allowed_joins` 表。

### 4.1 两个表的简单关联

场景：`orders` 关联 `customers`，通过 `orders.customer_id = customers.id`。

```http
POST /admin/schema/domains/orders/joins
Authorization: Bearer <token>
Content-Type: application/json

{
  "table": "orders",
  "joins": [
    {"table": "customers", "columns": {"customer_id": "id"}, "join_type": "LEFT"}
  ]
}
```

- `table` 当前表名（左侧表）
- `columns` 键值对：`{"当前表列名": "目标表列名"}`
- `join_type`：`LEFT` 或 `INNER`

### 4.2 复合关联（多列匹配）

场景：`order_items` 关联 `orders`，需同时匹配 `order_id` 且业务类型一致。

```http
POST /admin/schema/domains/orders/joins
Authorization: Bearer <token>
Content-Type: application/json

{
  "table": "order_items",
  "joins": [
    {"table": "orders",
     "columns": {"order_id": "order_id", "biz_type": "biz_type"},
     "join_type": "INNER"}
  ]
}
```

多个键会以 `AND` 组合成 ON 条件：

```sql
JOIN orders ON order_items.order_id=orders.order_id
           AND order_items.biz_type=orders.biz_type
```

### 4.3 跨表多跳（中间表）

场景：`orders` → `order_items` → `products`（查订单对应的商品信息）。

需要先登记每一条单跳 JOIN：

```http
POST /admin/schema/domains/orders/joins
{ "table": "orders", "joins": [
    {"table": "order_items", "columns": {"order_id": "order_id"}, "join_type": "INNER"}
] }

POST /admin/schema/domains/orders/joins
{ "table": "order_items", "joins": [
    {"table": "products", "columns": {"product_id": "id"}, "join_type": "LEFT"}
] }
```

### 4.4 登记 JOIN 的约束

- 左右表、左右列都必须在已登记元数据中
- JOIN 属于同一租户
- 只允许 `LEFT` / `INNER`，不支持任意 SQL 片段
- JOIN 只作为 LLM 的受控提示，最终 SQL 仍由 SQL Guard 校验

---

## 5. 只读权限授权

NL2SQL 用只读账号 `nl2sql_readonly` 执行查询。**这一步必须由管理员显式执行**，Registry 不会自动授权。

### 5.1 查看当前权限

```sql
SHOW GRANTS FOR 'nl2sql_readonly'@'%';
```

### 5.2 授权单张业务表

```sql
GRANT SELECT ON enterprise_agent.orders TO 'nl2sql_readonly'@'%';
GRANT SELECT ON enterprise_agent.order_items TO 'nl2sql_readonly'@'%';
GRANT SELECT ON enterprise_agent.products TO 'nl2sql_readonly'@'%';
FLUSH PRIVILEGES;
```

### 5.3 只授权、绝不授写权限

只读账号不应拥有：

```sql
INSERT / UPDATE / DELETE / DROP / ALTER / CREATE
```

只应拥有：

```sql
SELECT
```

> 安全原则：发布 Schema 只是登记元数据，不等于数据库账号已获得该表查询权限。**新增业务表时，登记 + 发布 + 显式 GRANT SELECT 三步缺一不可。**

---

## 6. 通过 NL2SQL 提问

发布并授权后，通过 Chat 提问：

```http
POST /chat
Authorization: Bearer <token>
Content-Type: application/json

{
  "question": "查询这个月订单总金额是多少",
  "conversation_id": "demo-01"
}
```

内部流程：

1. 意图路由识别为 `nl2sql`
2. 关键词/语义解析到已发布数据域 `orders`
3. 加载受控 Schema（含允许的 JOIN）给 LLM
4. LLM 生成单条 SELECT
5. SQL Guard 校验（只读、所有表必须在 allowlist、注入租户条件）
6. 用只读账号执行并返回结果

---

## 7. API 参考

管理端统一前缀 `/admin/schema`，写操作均需 `schema:admin`。

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/admin/schema/domains` | 列出数据域 |
| POST | `/admin/schema/domains` | 创建数据域（草稿） |
| GET | `/admin/schema/domains/{domain}/tables` | 列出域下表 |
| POST | `/admin/schema/domains/{domain}/tables` | 登记表 |
| POST | `/admin/schema/domains/{domain}/introspect` | 探测真实表结构 |
| GET | `/admin/schema/domains/{domain}/tables/{table}/columns` | 查看字段 |
| POST | `/admin/schema/domains/{domain}/columns` | 登记字段 |
| GET | `/admin/schema/domains/{domain}/joins` | 查看 JOIN |
| POST | `/admin/schema/domains/{domain}/joins` | 登记 JOIN |
| POST | `/admin/schema/domains/{domain}/publish` | 校验并发布 |

### 认证与错误

| 场景 | 状态码 |
|---|---|
| 无 Token | 401 |
| Token 无效/过期 | 401 |
| 无 `schema:admin` | 403 |
| 参数/标识符非法 | 400 |
| 数据域不存在 | 404/403 |
| 发布校验失败（无表/无可用字段/非法 JOIN） | 400 |
| 版本冲突 | 409 |

---

## 8. 快速自检脚本

真实 MySQL 连通性 + 全链路冒烟：

```bash
.venv/Scripts/python.exe scripts/smoke_schema_registry.py
```

流程：探测 `orders` → 登记临时域 → 发布 → Catalog 读取 → 清理。

---

## 9. 安全边界

- Schema Registry 只管理元数据，**不执行**用户 SQL
- NL2SQL 执行永远走只读账号 + SQL Guard
- 无 `tenant_id` 的表默认不可发布
- 敏感字段默认不可 selectable
- JOIN 只能使用登记过的受控关系
- `schema:admin` 与普通 `chat:ask` 权限隔离，LLM 无法触发管理操作
- 数据库授权必须由管理员显式 `GRANT SELECT`，Registry 不做自动授权
- **行级权限**：`sql_domain_permissions` 可按表设置行级过滤，按 `user` / `role` / `department` 主体匹配，deny 优先于 allow

## 9.1 行级权限（RLS）

行级权限让不同用户只能看到表中授权的行。

### 配置

在 `sql_domain_permissions` 中按表设置策略（需先运行迁移 `scripts/migrations/2026_09_03_row_policy_table_name.sql` 增加 `table_name` 列）：

```sql
-- 用户 user-test-001 只看自己的订单
INSERT INTO sql_domain_permissions
    (tenant_id, domain_id, table_name, subject_type, subject_id,
     row_predicate_template, allowed)
VALUES
    ('tenant-test', 'domain-orders', 'orders', 'user', 'user-test-001',
     'tenant_id = :tenant_id AND owner_id = :user_id', 1);
```

### 模板占位符（受限 DSL）

模板只允许以下受信任目标占位符，值由服务端从认证上下文绑定为 SQL 参数，绝不写入 SQL 文本：

| 占位符 | 类型 | 绑定值来源 |
|---|---|---|
| `:tenant_id` | 标量 | 认证 tenant |
| `:user_id` | 标量 | 认证用户 |
| `:role_names` | 列表 | 认证角色 |
| `:department_ids` | 列表 | 认证部门 |

模板禁止 `%`、注释、分号、写操作/关键字和未知占位符；列表为空时展开为 `(NULL)`（安全地不返回任何行）。

### 生效规则

- 匹配主体：按用户、角色、部门匹配当前登录者；
- **deny 优先**：任一匹配策略 `allowed=0` → 整表拒绝；
- allow 策略 `AND` 合并后注入 WHERE；
- 策略文本永远不会出现在 LLM prompt 或审计日志中。

### 当前限制（fail-closed）

行策略仅在**单表 SELECT** 上可靠生效。凡命中受保护表的复杂 SQL——`JOIN`、`UNION`、子查询、CTE——会被整体**拒绝执行**（fail-closed），而不是冒险把谓词注入错误的位置。启用 RLS 后，这些表暂不支持 JOIN 查询；后续升级到 AST 重写后可放宽该限制。

---

## 10. NL2SQL 查询流程详解

本节描述一次用户查询从 HTTP 请求到数据库返回结果的完整执行链路。NL2SQL 的核心原则是：**LLM 只负责提出 SQL 候选，程序负责决定是否允许执行**。

### 10.1 请求进入与身份建立

客户端调用：

```http
POST /chat
Authorization: Bearer <access_token>
Content-Type: application/json

{
  "question": "查询本月各地区订单总金额，按金额从高到低排列",
  "conversation_id": "orders-demo-01",
  "confirmed": false
}
```

处理步骤：

1. Bearer Token 由现有认证依赖验证；
2. 验证 token 是否存在、有效、未过期、未撤销；
3. 检查用户是否有 `chat:ask`；
4. 从可信的 `Principal` 生成 `RequestContext`；
5. `tenant_id`、`user_id`、角色、部门和权限全部来自认证上下文；
6. 用户问题、历史消息和 LLM 输出都不能覆盖这些身份字段。

`RequestContext` 是后续租户隔离和权限判断的唯一可信来源。

### 10.2 ChatService 统一编排

入口：

```text
app/chat/application/chat_service.py
```

`ChatService.ask()` 会：

1. 创建或读取会话；
2. 读取最近对话和结构化会话状态；
3. 进行追问理解、指代消解和上下文判断；
4. 只根据当前已解析问题进行意图路由；
5. 将请求分派给 RAG、SOP、NL2SQL 或混合处理器；
6. 保存会话状态、回答和审计事件。

上一轮是 NL2SQL 并不意味着本轮一定是 NL2SQL。只有会话理解明确是追问时，才会有限度地复用上轮 domain。

### 10.3 意图识别

当前使用规则路由与语义分类器组合：

```text
HybridIntentRouter
  ├─ RuleIntentRouter       先处理明确请求
  └─ SemanticIntentClassifier 规则不确定时再调用 LLM 分类
```

典型 NL2SQL 信号：

```text
查询、统计、多少、几笔、合计、总额、金额、占比、平均、排名、
本月、上月、同比、环比、趋势、明细、报表、数据
```

示例：

```text
统计本月有多少笔订单
→ nl2sql
```

知识问答与业务流程要区分：

```text
怎么做日志脱敏来保护隐私
→ knowledge_qa

怎么做采购申请的审批
→ sop
```

如果同时包含流程和数据任务，系统会分解成 MIXED；例如：

```text
采购超十万怎么审批，上个月有几单
→ 流程子任务 + 数据查询子任务
```

如果意图不明确，系统返回 clarification，不会盲目生成 SQL。

### 10.4 数据域解析

进入 `Nl2SqlService.answer()` 后，首先确定数据域：

```text
state.last_domain（仅在确认是追问且该域仍可用时）
        ↓
SchemaCatalog.resolve_domain(question)
```

`MysqlSchemaCatalog.resolve_domain()` 的规则是：

1. 只读取当前认证 tenant 的 active/published 域；
2. 加载 `sql_domain_keywords` 中的关键词和权重；
3. 对命中的关键词累计分数；
4. 长关键词会获得轻微 bonus；
5. 最高分明显领先时返回该 domain；
6. 多个 domain 分数接近时返回 `None`，要求用户澄清；
7. 无关键词命中时，再尝试 domain 名称匹配。

例如：

```text
问题：查询本月订单金额
关键词：订单、金额、销售额
结果：orders
```

未发布、disabled 或被当前用户拒绝的域不能参与解析。

### 10.5 加载受控 Schema

确定 domain 后，服务调用：

```python
schema = catalog.describe(domain, context=context)
allowed = catalog.allowed_tables(domain, context=context)
```

Catalog 只提供当前租户、当前用户可访问的已发布元数据，包括：

- domain 描述；
- 可用表和表描述；
- 字段名称、类型和业务名称；
- 字段能力标记；
- 允许的 JOIN；
- 租户过滤要求；
- 域级最大行数和超时限制（已登记且接入执行配置时）。

以下内容不会作为可用 Schema 交给 LLM：

- 未发布或 disabled 元数据；
- 其他 tenant 的表；
- 用户无权访问的 domain；
- 数据库密码、连接串；
- 任意原始行权限 SQL；
- 默认不可查询的敏感字段。

### 10.6 构造 LLM 生成提示

系统把受控 Schema 放入 prompt，并明确要求：

```text
- 只生成单条 SELECT
- 只能使用给出的表和字段
- 使用 MySQL 8.x 语法
- 禁止 INSERT/UPDATE/DELETE/DROP/ALTER
- 禁止多语句和注释注入
- 必须包含 tenant_id 过滤
- 只返回 SQL 代码块
```

示意 prompt：

```text
数据库方言：MySQL 8.x
数据域：orders

表 orders：订单主表
  order_id (varchar) 订单号 [select,filter]
  region (varchar) 地区 [select,filter,sort]
  amount (decimal) 金额 [select,aggregate,sort]
  created_at (datetime) 创建时间 [select,filter,sort]

允许关联：LEFT JOIN customers ON orders.customer_id=customers.id

问题：查询本月各地区订单总金额，按金额从高到低排列

要求：只生成单条 SELECT，必须包含 tenant_id 过滤。
```

Schema 是约束输入，不是授权本身；即使 prompt 要求安全，后续程序校验仍不可省略。

### 10.7 提取 SQL 候选

LLM 返回后，服务只接受：

```sql
```sql
SELECT ...
```
```

或以 `SELECT` 开头的纯文本。

无法提取合法 SELECT 时，返回 SQL 生成错误，不执行数据库请求。

LLM 生成的 SQL 仍然是不可信输入，不能因为模型是内部模型就跳过 Guard。

### 10.8 SQL Guard 校验

入口：

```text
app/chat/application/nl2sql/sql_guard.py
```

当前 Guard 负责基础策略校验：

- 只允许 SELECT；
- 拒绝写操作关键字；
- 拒绝多语句；
- 拒绝 SQL 注释；
- 拒绝 `INTO OUTFILE` / `INTO DUMPFILE`；
- 默认拒绝 `SELECT *`；
- 检查 SQL 中引用的**每一张物理表**是否属于当前 domain allowlist；不能用一张合法表掩盖另一张未授权表；
- 支持 FROM/JOIN、逗号多表、UNION、表别名和常见只读 CTE 的表引用识别；
- 函数参数、SELECT 列名不会被误当成表名；
- 未配置 allowlist，或 SQL 没有可识别的表引用时拒绝执行；
- 拒绝 SQL 中引用任何标记为 `sensitive` 的字段（无论出现在 SELECT、WHERE、ORDER BY 还是 GROUP BY）；
- 字符串字面量中的敏感字段名不会误报。

例如，下面的 SQL 会被拒绝：

```sql
SELECT o.order_id
FROM orders o
JOIN users u ON o.user_id = u.id
```

当 allowlist 只有 `orders` 时，Guard 会拒绝 `users`，即使 `orders` 是允许表。

Guard 失败时立即拒绝，不连接业务数据库。

> 当前 Guard 已实现表级全量 allowlist 与敏感字段拦截，但仍是无外部 parser 的保守词法校验，不等同于完整 AST 分析。列级能力（selectable/filterable/sortable/aggregatable）、敏感字段脱敏（masking）、复杂 JOIN 语义和每张表的 tenant 条件仍应继续升级为 AST 级校验。Schema Registry 不会因此替代 Guard。

### 10.9 服务端强制租户条件

SQL 候选通过基础 Guard 后，`Nl2SqlService` 使用认证 context 中的 tenant：

```sql
WHERE tenant_id = '<来自 RequestContext 的 tenant_id>'
```

重要原则：

- 不信任 LLM 自己填写的 tenant_id；
- 不信任用户问题中的 tenant_id；
- 不信任请求 body 中的 tenant_id；
- 只使用认证上下文中的 tenant_id；
- tenant_id 会进行引号转义。

如果 context 没有 tenant_id，查询直接拒绝。

当前实现是文本级租户条件注入，后续复杂 SQL 应升级为 AST 级注入，并确保每个需要租户隔离的表都受保护。

### 10.10 使用只读执行器执行

通过：

```text
app/chat/adapters/mysql_readonly_executor.py
```

使用 `.env` 中的只读连接：

```dotenv
SQL_READONLY_HOST=...
SQL_READONLY_PORT=3306
SQL_READONLY_USER=nl2sql_readonly
SQL_READONLY_PASSWORD=...
SQL_READONLY_DB=enterprise_agent
```

执行器负责：

1. 使用独立只读账号连接；
2. 设置只读事务/会话属性；
3. 应用 timeout；
4. 限制最大返回行数；
5. 执行 SQL；
6. 返回列名、行数据、行数和 query ID；
7. 不提供写入业务表的能力。

数据库层仍必须显式授权：

```sql
GRANT SELECT ON enterprise_agent.orders TO 'nl2sql_readonly'@'%';
```

应用层 Guard 和数据库账号权限是两道独立防线，不能互相替代。

### 10.11 执行失败与一次重写

如果只读执行器返回可恢复的 SQL 错误，服务允许 LLM **最多重写一次**：

```text
数据库错误
  → 把错误类型、原问题、原 SQL 反馈给 LLM
  → 生成候选 SQL
  → 再次执行 validate_sql()
  → 再次强制 tenant 条件
  → 最多执行一次重试
```

重写请求不能绕过：

- 表 allowlist；
- SELECT-only 检查；
- tenant 注入；
- 只读执行器；
- timeout 和最大行数。

第二次仍失败则返回脱敏错误，不把数据库凭据或完整内部连接信息暴露给用户。

### 10.12 结果解释

执行成功后，服务只取有限结果预览交给 LLM 生成中文说明：

```text
原问题 + 数据域 + 前几行结果 + 总行数
```

结果解释阶段：

- 不重新生成或执行 SQL；
- 只依据本次查询结果；
- 不补造数据库中不存在的数据；
- 结果中的敏感字段仍应在查询列策略和数据库权限层控制；
- LLM 解释失败不应触发第二次业务查询。

### 10.13 返回响应与审计

成功响应示例：

```json
{
  "answer": "本月华东地区订单总金额为……",
  "status": "answered",
  "mode": "nl2sql",
  "conversation_id": "orders-demo-01",
  "sql": {
    "query_id": "...",
    "domain": "orders",
    "columns": ["region", "total_amount"],
    "row_count": 4
  },
  "warnings": []
}
```

系统还会保存：

- 问题和解析后的 domain；
- SQL 生成/Guard/执行状态；
- query ID、行数和耗时；
- trace ID；
- 错误类型和脱敏错误信息；
- 会话状态。

生产日志不应保存数据库密码、access token 或未脱敏的敏感结果。

### 10.14 完整流程图

```text
HTTP POST /chat
    │
    ├─ Bearer Token 验证 + chat:ask
    │
    ├─ Principal → RequestContext
    │       └─ tenant/user/roles/departments/permissions
    │
    ├─ ChatService.ask()
    │       ├─ 会话与追问理解
    │       └─ IntentRouter
    │
    ├─ Nl2SqlService.answer()
    │       ├─ resolve_domain()
    │       ├─ describe() + allowed_tables()
    │       ├─ LLM 生成 SELECT 候选
    │       ├─ SQL Guard
    │       ├─ 服务端注入认证 tenant_id
    │       ├─ ReadonlySqlExecutor
    │       │       └─ SQL_READONLY_* / nl2sql_readonly
    │       ├─ 失败时最多重写一次
    │       └─ LLM 解释有限结果
    │
    ├─ 保存会话与审计
    │
    └─ 返回 ChatResult
```

### 10.15 查询失败排查顺序

遇到查询失败时，按以下顺序定位：

| 现象 | 优先检查 |
|---|---|
| 返回 `clarification` | 问题是否包含明确业务域关键词，是否命中多个域 |
| 返回 `no_context` | 是否被错误路由到 SOP/RAG，是否存在对应知识/SOP 数据 |
| 域解析失败 | domain 是否 active、关键词是否登记、用户是否有域权限 |
| Guard 拒绝 | 是否为 SELECT、引用的每张表是否都在 allowlist、是否包含禁用语法 |
| 数据库拒绝权限 | `SHOW GRANTS FOR 'nl2sql_readonly'@'%';` |
| 找不到表 | 业务表真实存在、数据库名正确、Schema 已发布 |
| 找不到列 | 列是否登记且真实存在，字段是否 selectable |
| 返回空数据 | tenant_id、时间条件、业务数据和行权限是否正确 |
| 超时/行数过多 | domain 限制、查询条件、索引和只读执行器配置 |
| 返回 `no_sop` | 问题被识别为 SOP，应检查意图路由或改用知识问答表达 |

---

## 11. 最小查询检查清单

上线一个新数据域前，逐项确认：

- [ ] 真实业务表已经创建；
- [ ] `tenant_id` 策略已确认；
- [ ] Schema domain 已创建；
- [ ] 关键词已登记；
- [ ] 真实表已 introspect；
- [ ] 表已登记；
- [ ] 需要输出的列 `selectable=true`；
- [ ] 敏感列默认 `selectable=false`；
- [ ] JOIN 已登记且左右列真实存在；
- [ ] domain 已 publish；
- [ ] `nl2sql_readonly` 已获得目标表的 `SELECT`；
- [ ] `SHOW GRANTS` 已复核没有写权限；
- [ ] `scripts/smoke_schema_registry.py` 已通过；
- [ ] 用真实自然语言问题完成一次 `/chat` 验证；
- [ ] 业务表有当前 tenant 的测试数据；
- [ ] 复杂查询已验证超时、空结果和越权场景。
