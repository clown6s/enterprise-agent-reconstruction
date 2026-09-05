# 删除数据域

只删除 Schema 元数据，不删除业务表。

## 1. 确认 ID

```http
GET /admin/schema/domains
Authorization: Bearer <SCHEMA_ADMIN_TOKEN>
```

使用响应中的原始 `domain_id`，不要改写。

## 2. 删除行策略（可选）

```http
GET /admin/schema/domains/<DOMAIN_ID>/policies
Authorization: Bearer <SCHEMA_ADMIN_TOKEN>
```

```http
DELETE /admin/schema/domains/<DOMAIN_ID>/policies/<PERMISSION_ID>
Authorization: Bearer <SCHEMA_ADMIN_TOKEN>
```

## 3. 删除数据域

确认租户和数据域 ID 后执行：

```http
DELETE /admin/schema/domains/<DOMAIN_ID>
Authorization: Bearer <SCHEMA_ADMIN_TOKEN>
```

响应：

```json
{"domain_id":"<DOMAIN_ID>","deleted":true}
```

## 4. 验证

```http
GET /admin/schema/domains
Authorization: Bearer <SCHEMA_ADMIN_TOKEN>
```

确认目标域不再出现，其他数据域仍存在。
