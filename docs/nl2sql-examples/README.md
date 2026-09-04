# NL2SQL 完整流程示例

本目录把 `docs/nl2sql.md` 中的长示例拆成可独立阅读的完整流程。所有请求均以当前代码中的实际 API 为准。

## 推荐顺序

| 文件 | 内容 |
|---|---|
| [orders-single-table.md](orders-single-table.md) | 单表数据域：订单查询 |
| [customer-orders-join.md](customer-orders-join.md) | 两表 JOIN：订单与客户 |
| [library-books-join.md](library-books-join.md) | `books` 与 `book_authors` 完整示例 |
| [row-policy.md](row-policy.md) | 行级权限配置与验证 |
| [domain-cleanup.md](domain-cleanup.md) | 数据域删除、外键和清理 |

## 重要说明

- 这些文件是 Markdown 操作指南，不会自动执行任何命令。
- 业务表、字段、数据库名、租户和账号必须以你的环境为准；先执行 `SHOW CREATE TABLE` 或接口 `introspect`，再填写请求。
- 当前仓库没有 `scripts/chat_schema.sql`、`scripts/test_data.sql`，文档不能把它们当作仓库内可直接执行的文件。
- `domain_id` 必须使用创建接口响应中的真实值。历史 ID 可能包含连字符（例如 `domain-orders`），必须原样使用，不能擅自改成 `domain_orders`。
- JSON 代码块是合法 JSON，不写 `//` 注释；说明放在代码块外。
- Schema 发布不等于数据库授权。只读账号必须另外获得目标业务表的 `SELECT` 权限。
- LLM 只生成 SQL 候选，不生成 `tenant_id` 条件。租户隔离由服务端从认证上下文读取并以参数方式注入。
- 启用列白名单后，每一张被 SQL 引用的物理表都必须登记列；缺少列白名单会 fail-closed 拒绝。

## 公共变量

下面的占位符只用于说明，不能直接当成真实值：

```text
BASE_URL=http://127.0.0.1:8000
SCHEMA_ADMIN_TOKEN=<拥有 schema:admin 的 token>
ACCESS_TOKEN=<拥有 chat:ask 的 token>
TENANT_ID=<认证用户所属租户>
DB_NAME=<业务数据库名>
DOMAIN_ID=<创建接口返回的 domain_id>
```

管理员 token 示例：

```http
POST /auth/login
Content-Type: application/json

{
  "tenant_id": "<TENANT_ID>",
  "username": "<管理员用户名>",
  "password": "<管理员密码>"
}
```

登录用户必须拥有 `schema:admin`。查询 `/chat` 使用的 token 必须拥有 `chat:ask`；二者可以是同一个用户，也可以是不同用户。

## 统一登记顺序

```text
确认真实业务表和字段
→ 创建数据域
→ 保存响应中的 domain_id
→ introspect
→ 登记表
→ 登记全部需要使用的列
→ 登记 JOIN / 行权限（如需要）
→ publish
→ 给只读账号显式 GRANT SELECT
→ 调用 /chat 验证
```

## 登记列参数说明

列登记接口是：

```http
POST /admin/schema/domains/<DOMAIN_ID>/columns
Authorization: Bearer <SCHEMA_ADMIN_TOKEN>
Content-Type: application/json
```

请求体外层必须包含：

| 参数 | 是否必填 | 含义 |
|---|---:|---|
| `table` | 是 | 当前要登记列的真实表名，必须先通过 `/tables` 登记；必须与数据库表名完全一致 |
| `columns` | 是 | 列对象数组，至少包含一项；数组最多 500 项 |

每个 `columns` 元素的参数：

| 参数 | 是否必填 | 含义和配置建议 |
|---|---:|---|
| `column_name` | 是 | 数据库真实列名，必须与 `introspect` 或 `SHOW CREATE TABLE` 一致；不能写业务别名 |
| `data_type` | 是 | 列的数据类型，例如 `varchar`、`decimal`、`datetime`；应填写 introspect 返回的真实类型 |
| `business_name` | 否 | 面向 LLM 和管理员的业务名称，例如“订单金额”；不改变数据库列名 |
| `description` | 否 | 列用途说明，例如“仅用于 JOIN”；帮助模型理解使用边界 |
| `selectable` | 否，默认 `true` | 是否允许作为最终 `SELECT` 输出；内部 ID、租户字段、JOIN 键通常设为 `false` |
| `filterable` | 否，默认 `true` | 是否允许用于过滤条件或行权限模板；`tenant_id` 若出现在行权限模板中必须为 `true` |
| `sortable` | 否，默认 `false` | 是否允许用于 `ORDER BY`；日期、金额、状态等确实需要排序时设为 `true` |
| `aggregatable` | 否，默认 `false` | 是否允许参与 `SUM`、`AVG` 等聚合；金额、数量等数值列才设为 `true` |
| `sensitive` | 否，默认 `false` | 是否为敏感列；设为 `true` 后 SQL Guard 会拒绝引用，不能仅靠 `masking_rule` 认为它仍可查询 |
| `masking_rule` | 否 | 脱敏规则名称元数据；当前登记接口保存该值，但不要把它当作已经自动执行的查询脱敏保证 |

### 常用配置模板

普通可输出字段：

```json
{
  "column_name": "amount",
  "data_type": "decimal",
  "business_name": "订单金额",
  "description": "订单金额，可用于统计",
  "selectable": true,
  "filterable": true,
  "sortable": true,
  "aggregatable": true,
  "sensitive": false
}
```

仅用于租户隔离或 JOIN 的字段：

```json
{
  "column_name": "tenant_id",
  "data_type": "varchar",
  "business_name": "租户标识",
  "description": "仅用于服务端租户隔离",
  "selectable": false,
  "filterable": true,
  "sortable": false,
  "aggregatable": false,
  "sensitive": false
}
```

JOIN 键的配置方式：

```json
{
  "column_name": "author_id",
  "data_type": "varchar",
  "business_name": "作者编号",
  "description": "仅用于 JOIN",
  "selectable": false,
  "filterable": true,
  "sortable": false,
  "aggregatable": false,
  "sensitive": false
}
```

> `selectable=false` 不等于列不存在，也不等于不能 JOIN。JOIN 键必须仍然登记在对应表的 `columns` 数组中，否则 SQL Guard 会拒绝 JOIN。

## 没有登记列会怎样

当前代码采用 **fail-closed（失败关闭）**：

1. 只登记数据域和表、没有登记任何列：调用 NL2SQL 时返回类似：
   ```text
   表 orders 未登记列白名单，拒绝执行
   ```
2. 某一张 JOIN 表登记了列，另一张没有登记：整个查询拒绝，不会只放行已登记的那张表。
3. 登记了列但 SQL 使用未登记字段：返回类似：
   ```text
   表 orders 引用了未授权字段: create_time
   ```
4. 字段在数据库中不存在：正常情况下应在 publish 阶段被拒绝；如果元数据未正确发布或旧流程绕过校验，数据库可能返回 `Unknown column`，应回到 introspect 核对真实字段。
5. 只登记列但没有先登记所属表：会因 `sql_allowed_columns` 的外键约束产生 `IntegrityError`；正确顺序是先 `/tables`，再 `/columns`。
6. 只登记列但没有 publish：列仍是草稿元数据，NL2SQL 的 Catalog 读不到，查询可能提示域或列不可用。
7. 只 publish 没有给只读账号授权：Schema 校验可能成功，但执行 SQL 时会因数据库权限不足失败。

fail-closed 的目的，是让“未配置”变成明确拒绝，而不是让 LLM 猜列名并把错误 SQL 送到数据库。每张会被 SQL 引用的物理表都应登记所有可能用到的列，包括输出列、过滤列、排序列、聚合列和 JOIN 键。

## 给只读账号添加权限

NL2SQL 用只读账号 `nl2sql_readonly` 执行查询。**Schema 发布不会自动授予数据库权限**，必须显式为该账号授予目标业务表的 `SELECT` 权限，否则查询会失败。这一步由数据库管理员在业务数据库执行，不经过 `/admin/schema`。

查看当前只读账号权限：

```sql
SHOW GRANTS FOR 'nl2sql_readonly'@'%';
```

为一张业务表授权：

```sql
GRANT SELECT ON <DB_NAME>.<表名> TO 'nl2sql_readonly'@'%';
```

一次为多张表授权：

```sql
GRANT SELECT ON <DB_NAME>.orders       TO 'nl2sql_readonly'@'%';
GRANT SELECT ON <DB_NAME>.order_customers TO 'nl2sql_readonly'@'%';
GRANT SELECT ON <DB_NAME>.books        TO 'nl2sql_readonly'@'%';
GRANT SELECT ON <DB_NAME>.book_authors TO 'nl2sql_readonly'@'%';
FLUSH PRIVILEGES;
```

安全要求：

- 只授予 `SELECT`，不要授予 `INSERT`、`UPDATE`、`DELETE`、`DROP`、`ALTER`、`CREATE`；
- 每张被 SQL 引用的真实业务表都要单独授权；
- 授权后运行 `SHOW GRANTS FOR 'nl2sql_readonly'@'%'` 确认没有多余的写权限；
- 如果你的只读账号名、数据库名与上述不同，用实际值替换。

> 应用层的 SQL Guard 和数据库账号权限是两道独立防线。即使 Schema 已发布，缺少数据库 `GRANT SELECT` 仍会导致查询失败。

## 统一错误排查

错误响应统一为：

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "具体错误信息",
    "details": []
  },
  "trace_id": "请求对应的 trace_id"
}
```

用响应中的 `trace_id` 查询服务日志或 Elasticsearch。常见错误：

| 错误 | 处理 |
|---|---|
| `数据域ID无效` | 使用创建接口返回的原始 `domain_id`；历史连字符 ID 不要改写 |
| `表 xxx 未登记列白名单，拒绝执行` | 给该表登记列并重新发布 |
| `表 xxx 引用了未授权字段` | 核对真实字段名，并在对应表登记 |
| `IntegrityError` / 外键失败 | 先登记父数据域和表，再登记列或策略 |
| `Unknown column` | 先用 `introspect` 或 `SHOW CREATE TABLE` 确认字段，不要让模型猜字段 |
| `服务暂时不可用` | 按 `trace_id` 查询服务端日志，检查 MySQL、LLM 和只读账号 |

## 验证原则

只有在你的环境实际完成请求并检查响应后，才能判定流程成功。LLM 返回的 SQL 可能存在别名、空格和排序差异，应验证 `mode`、`status`、`sql.domain`、`sql.query_id`、`trace_id` 和业务结果，不要用整段 SQL 字符串做脆弱的完全匹配。
