# 行级权限（RLS）流程

行级权限用于在租户隔离之外增加用户、角色或部门维度的行过滤。所有策略都由服务端从认证上下文绑定参数，不能由 LLM 或请求体提供身份值。

## 前置条件

1. 目标数据域已创建，且 `domain_id` 使用真实返回值。
2. 目标表已通过 `POST /domains/{domain_id}/tables` 登记。
3. 策略引用的每个列已通过 `/columns` 登记。
4. 策略引用的列必须 `filterable=true`，且不能 `sensitive=true`。
5. 若模板引用 `tenant_id`，该列应配置 `selectable=false, filterable=true, sensitive=false`。

## 允许的模板占位符

```text
:tenant_id
:user_id
:role_names
:department_ids
```

占位符的实际值由认证上下文提供，最终作为 DB-API 参数绑定。禁止在模板中写入真实租户、用户或角色值。

模板禁止：

- `%`；
- `--`、`/*`、`*/` 注释；
- 分号；
- INSERT、UPDATE、DELETE、DROP、ALTER、CREATE 等写操作/关键字；
- 未知占位符。

## 1. 创建策略

以下示例使用当前用户 `user-test-001`，目标表和字段必须真实存在：

```http
POST /admin/schema/domains/<DOMAIN_ID>/policies
Authorization: Bearer <SCHEMA_ADMIN_TOKEN>
Content-Type: application/json

{
  "table": "orders",
  "subject_type": "user",
  "subject_id": "user-test-001",
  "predicate_template": "owner_id = :user_id",
  "allowed": true
}
```

如果策略需要同时限定租户，可以写：

```json
{
  "table": "orders",
  "subject_type": "user",
  "subject_id": "user-test-001",
  "predicate_template": "tenant_id = :tenant_id AND owner_id = :user_id",
  "allowed": true
}
```

这里的 JSON 不包含注释；字段说明放在 JSON 外。`tenant_id` 的重复条件是安全且可用的，但服务端本身已经强制注入租户条件。

## 2. 主体类型

`subject_type` 只能是：

```text
user
role
department
```

- `user`：`subject_id` 使用用户 ID；
- `role`：`subject_id` 使用角色名称，例如 `employee`，不是角色 ID，也不是 `role-employee`；
- `department`：`subject_id` 使用认证上下文中的部门 ID。

## 3. 查看策略

```http
GET /admin/schema/domains/<DOMAIN_ID>/policies
Authorization: Bearer <SCHEMA_ADMIN_TOKEN>
```

策略文本用于管理员查看，不会进入 NL2SQL prompt，也不写入普通问答审计 payload。

## 4. 删除单条策略

先从 GET 返回中确认 `permission_id`，再删除：

```http
DELETE /admin/schema/domains/<DOMAIN_ID>/policies/<PERMISSION_ID>
Authorization: Bearer <SCHEMA_ADMIN_TOKEN>
```

## 5. 生效规则

- 匹配用户、角色、部门的策略；
- 任一匹配策略 `allowed=false` 时，拒绝访问目标表（deny 优先）；
- 匹配的 allow 策略以 AND 组合；
- 服务端额外为每张物理表注入 `tenant_id = %s`；
- `JOIN`、`UNION`、子查询和 CTE 中的受管控物理表由 AST 逐表重写；
- 找不到物理表、SQL 无法解析、参数数量不一致或无法安全重写时 fail-closed。

## 6. 用 JOIN 验证

启用 RLS 后，JOIN 仍可使用。JOIN 两侧表和 JOIN 键都必须已登记，且每张物理表都必须有列白名单。

```http
POST /chat
Authorization: Bearer <ACCESS_TOKEN>
Content-Type: application/json
X-Trace-Id: rls-join-001

{
  "question": "查询我负责的订单及客户名称",
  "conversation_id": "rls-join-001"
}
```

用响应中的 `trace_id` 查询日志；不要用响应里的模型 SQL 推断实际绑定的租户值，真实值不会拼入 SQL 文本。

## 7. 常见错误

| 错误 | 原因 | 修复 |
|---|---|---|
| `策略目标表未登记` | 目标表没有先登记 | 先调用 tables 接口 |
| `策略引用了未登记或未授权的字段` | 模板字段不在列白名单 | 先登记真实字段 |
| `策略引用了敏感或不可过滤的字段` | `filterable=false` 或 `sensitive=true` | 调整字段能力，重新登记 |
| `表 xxx 未登记列白名单` | 查询引用的物理表未登记任何列 | 登记该表全部需要字段并 publish |
| `行级权限拒绝访问该表` | 匹配到 deny 策略 | 检查主体和 allowed 状态 |
