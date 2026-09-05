# 行级权限

前置：目标表已登记，策略引用的列已登记且 `filterable=true`、`sensitive=false`。占位符由服务端从认证上下文绑定：

```text
:tenant_id
:user_id
:role_names
:department_ids
```

## 1. 创建策略

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

`subject_type` 只允许 `user`、`role`、`department`。

## 2. 查看

```http
GET /admin/schema/domains/<DOMAIN_ID>/policies
Authorization: Bearer <SCHEMA_ADMIN_TOKEN>
```

## 3. 删除

先从 GET 响应取 `permission_id`：

```http
DELETE /admin/schema/domains/<DOMAIN_ID>/policies/<PERMISSION_ID>
Authorization: Bearer <SCHEMA_ADMIN_TOKEN>
```

## 4. 验证

```http
POST /chat
Authorization: Bearer <ACCESS_TOKEN>
Content-Type: application/json

{
  "question": "查询我负责的订单及客户名称",
  "conversation_id": "rls-001"
}
```

匹配的 allow 策略组合，任一 deny 策略拒绝。服务端始终注入 `tenant_id = %s`。模板禁止 `%`、注释、分号、写关键字和未知占位符。