# 数据域删除与关联清理

本示例用于清理测试数据域的元数据，不删除真实业务表，也不删除 `auth_tenants` 租户本身。

## 重要警告

数据域删除不可恢复。执行前必须确认：

- `tenant_id` 正确；
- `domain_id` 正确；
- 要删除的是测试域，而不是生产域；
- `library` 等需要保留的域不在删除范围内。

历史数据域 ID 可能包含连字符，例如 `domain-orders`。必须使用列表接口返回的原始值，不要改成 `domain_orders`。

## 1. 删除单条行策略

如果只想撤销一条行权限，先查询 `permission_id`：

```http
GET /admin/schema/domains/<DOMAIN_ID>/policies
Authorization: Bearer <SCHEMA_ADMIN_TOKEN>
```

确认后：

```http
DELETE /admin/schema/domains/<DOMAIN_ID>/policies/<PERMISSION_ID>
Authorization: Bearer <SCHEMA_ADMIN_TOKEN>
```

## 2. 删除整个数据域（推荐接口）

```http
DELETE /admin/schema/domains/<DOMAIN_ID>
Authorization: Bearer <SCHEMA_ADMIN_TOKEN>
X-Trace-Id: cleanup-001
```

成功返回：

```json
{
  "domain_id": "<DOMAIN_ID>",
  "deleted": true
}
```

接口只删除当前认证租户下的目标域，并在事务中清理关联元数据。数据域不存在或 ID 不合法会返回错误，不会删除其他域。

## 3. 删除前检查

```http
GET /admin/schema/domains
Authorization: Bearer <SCHEMA_ADMIN_TOKEN>
```

如果列表中返回的是 `domain-orders`，删除请求必须是：

```text
DELETE /admin/schema/domains/domain-orders
```

不能改为 `domain_orders`。

## 4. 关联表和外键顺序

当前元数据关联关系：

```text
sql_allowed_columns       → sql_allowed_tables
sql_allowed_tables        → sql_data_domains
sql_domain_keywords       → sql_data_domains
sql_domain_permissions    → sql_data_domains
sql_schema_versions       → sql_data_domains
sql_allowed_joins         → sql_schema_versions
sql_schema_change_logs    → sql_schema_versions
sql_data_domains           → auth_tenants
```

应用层事务清理时，必须先清理子表，再清理父表：

```text
sql_schema_change_logs
→ sql_allowed_joins
→ sql_schema_versions
→ sql_domain_permissions
→ sql_allowed_columns
→ sql_allowed_tables
→ sql_domain_keywords
→ sql_data_domains
```

`sql_allowed_joins` 和 `sql_schema_change_logs` 没有直接的 `domain_id`，需要通过 `sql_schema_versions.version_id` 定位域。

## 5. 外键级联迁移（可选）

仓库提供：

```text
scripts/migrations/2026_09_04_schema_fk_cascade.sql
```

执行前先在目标数据库核对外键名称：

```sql
SELECT
    TABLE_NAME,
    CONSTRAINT_NAME,
    REFERENCED_TABLE_NAME
FROM information_schema.KEY_COLUMN_USAGE
WHERE TABLE_SCHEMA = DATABASE()
  AND TABLE_NAME IN (
      'sql_data_domains',
      'sql_allowed_tables',
      'sql_allowed_columns',
      'sql_domain_keywords',
      'sql_domain_permissions',
      'sql_schema_versions',
      'sql_allowed_joins',
      'sql_schema_change_logs'
  )
  AND REFERENCED_TABLE_NAME IS NOT NULL;
```

再由数据库管理员执行迁移：

```bash
mysql -h <MYSQL_HOST> -P 3306 \
  -u <MYSQL_USER> -p <DB_NAME> \
  < scripts/migrations/2026_09_04_schema_fk_cascade.sql
```

注意：迁移文件在仓库中，不代表你的线上数据库已经执行。`sql_data_domains → auth_tenants` 故意保持 `RESTRICT`，避免删除租户时级联删除全部 Schema 元数据。

## 6. 未执行级联迁移时的手工 SQL

优先使用删除接口。只有在接口不可用且经过管理员复核时，才按外键顺序手动删除。所有语句必须带当前租户和精确 `domain_id`，并包在事务中：

```sql
START TRANSACTION;

DELETE l
FROM sql_schema_change_logs AS l
JOIN sql_schema_versions AS v
  ON v.tenant_id = l.tenant_id
 AND v.version_id = l.version_id
WHERE l.tenant_id = '<TENANT_ID>'
  AND v.domain_id = '<DOMAIN_ID>';

DELETE j
FROM sql_allowed_joins AS j
JOIN sql_schema_versions AS v
  ON v.tenant_id = j.tenant_id
 AND v.version_id = j.version_id
WHERE j.tenant_id = '<TENANT_ID>'
  AND v.domain_id = '<DOMAIN_ID>';

DELETE FROM sql_schema_versions
WHERE tenant_id = '<TENANT_ID>' AND domain_id = '<DOMAIN_ID>';

DELETE FROM sql_domain_permissions
WHERE tenant_id = '<TENANT_ID>' AND domain_id = '<DOMAIN_ID>';

DELETE FROM sql_allowed_columns
WHERE tenant_id = '<TENANT_ID>' AND domain_id = '<DOMAIN_ID>';

DELETE FROM sql_allowed_tables
WHERE tenant_id = '<TENANT_ID>' AND domain_id = '<DOMAIN_ID>';

DELETE FROM sql_domain_keywords
WHERE tenant_id = '<TENANT_ID>' AND domain_id = '<DOMAIN_ID>';

DELETE FROM sql_data_domains
WHERE tenant_id = '<TENANT_ID>' AND domain_id = '<DOMAIN_ID>';

COMMIT;
```

任一步出错执行：

```sql
ROLLBACK;
```

## 7. 删除后验证

```sql
SELECT tenant_id, domain_id, domain_name
FROM sql_data_domains
WHERE tenant_id = '<TENANT_ID>'
  AND domain_id = '<DOMAIN_ID>';
```

应返回空集。再检查子表：

```sql
SELECT COUNT(*) AS total
FROM sql_allowed_tables
WHERE tenant_id = '<TENANT_ID>' AND domain_id = '<DOMAIN_ID>';

SELECT COUNT(*) AS total
FROM sql_allowed_columns
WHERE tenant_id = '<TENANT_ID>' AND domain_id = '<DOMAIN_ID>';

SELECT COUNT(*) AS total
FROM sql_domain_permissions
WHERE tenant_id = '<TENANT_ID>' AND domain_id = '<DOMAIN_ID>';

SELECT COUNT(*) AS total
FROM sql_schema_versions
WHERE tenant_id = '<TENANT_ID>' AND domain_id = '<DOMAIN_ID>';
```

这些计数都应为 `0`。最后重新调用 `GET /admin/schema/domains`，确认保留的数据域仍在、目标域不再出现。
