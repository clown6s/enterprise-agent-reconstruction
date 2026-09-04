# 单表订单查询流程

本示例演示把一张真实的 `orders` 表登记为 NL2SQL 数据域。示例字段必须替换为你通过 `introspect` 或 `SHOW CREATE TABLE` 确认的真实字段。

## 执行前检查

- 管理接口已启动，例如 `http://127.0.0.1:8000`。
- 已取得拥有 `schema:admin` 的管理员 token。
- 已取得拥有 `chat:ask` 的查询 token。
- `orders` 真实表已经存在，且包含 `tenant_id`。
- 只读账号后续会获得 `orders` 的 `SELECT` 权限。

## 1. 确认真实结构

```sql
SHOW TABLES LIKE 'orders';
SHOW CREATE TABLE orders;
```

再调用接口探测字段：

```http
POST /admin/schema/domains/orders/introspect
Authorization: Bearer <SCHEMA_ADMIN_TOKEN>
Content-Type: application/json

{
  "tables": ["orders"],
  "include_columns": true
}
```

响应中的 `column_name` 和 `data_type` 才是登记依据。不要根据“创建时间”等中文含义自行猜 `create_time`、`created_at` 等字段。

## 2. 创建数据域

```http
POST /admin/schema/domains
Authorization: Bearer <SCHEMA_ADMIN_TOKEN>
Content-Type: application/json

{
  "name": "orders",
  "description": "销售订单数据域",
  "keywords": ["订单", "orders", "销售额", "金额"]
}
```

保存响应中的真实 `domain_id`：

```json
{
  "domain_id": "orders",
  "domain_name": "orders",
  "status": "draft"
}
```

后续所有 `/admin/schema/domains/{domain}` 中的 `{domain}` 都替换成这个值，不要自行修改。

## 3. 登记表

```http
POST /admin/schema/domains/<DOMAIN_ID>/tables
Authorization: Bearer <SCHEMA_ADMIN_TOKEN>
Content-Type: application/json

{
  "table": "orders",
  "description": "订单主表",
  "required_tenant_filter": true
}
```

必须先登记表，再登记列。否则 `sql_allowed_columns` 的外键可能报错。

## 4. 登记列

下面假设 `introspect` 确认了这些字段；请按你的实际结构增删，不能照抄不存在的列：

```http
POST /admin/schema/domains/<DOMAIN_ID>/columns
Authorization: Bearer <SCHEMA_ADMIN_TOKEN>
Content-Type: application/json

{
  "table": "orders",
  "columns": [
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
    },
    {
      "column_name": "order_id",
      "data_type": "varchar",
      "business_name": "订单号",
      "description": "订单唯一编号",
      "selectable": true,
      "filterable": true,
      "sortable": true,
      "aggregatable": false,
      "sensitive": false
    },
    {
      "column_name": "amount",
      "data_type": "decimal",
      "business_name": "订单金额",
      "description": "订单金额",
      "selectable": true,
      "filterable": true,
      "sortable": true,
      "aggregatable": true,
      "sensitive": false
    },
    {
      "column_name": "created_at",
      "data_type": "datetime",
      "business_name": "创建时间",
      "description": "订单创建时间",
      "selectable": true,
      "filterable": true,
      "sortable": true,
      "aggregatable": false,
      "sensitive": false
    }
  ]
}
```

如果实际 `introspect` 返回的时间字段不是 `created_at`，必须替换为实际名称。`tenant_id` 不应 `selectable`，但如果行权限模板引用它，必须 `filterable=true` 且 `sensitive=false`。

## 5. 发布

```http
POST /admin/schema/domains/<DOMAIN_ID>/publish
Authorization: Bearer <SCHEMA_ADMIN_TOKEN>
Content-Type: application/json

{
  "version": 1,
  "comment": "首次发布订单数据域"
}
```

发布会检查真实表、已登记列、租户字段和其他元数据。返回成功后状态才会变成 `active`。

## 6. 授权只读账号

在业务数据库执行，账号和数据库名按环境替换：

```sql
GRANT SELECT ON <DB_NAME>.orders
TO 'nl2sql_readonly'@'%';

FLUSH PRIVILEGES;
SHOW GRANTS FOR 'nl2sql_readonly'@'%';
```

Schema 发布不会自动执行 `GRANT`。

## 7. 调用问答接口

```http
POST /chat
Authorization: Bearer <ACCESS_TOKEN>
Content-Type: application/json
X-Trace-Id: orders-example-001

{
  "question": "查询这个月订单总金额是多少",
  "conversation_id": "orders-example-001"
}
```

验证响应：

- `status` 为 `answered`；
- `mode` 为 `nl2sql`；
- `sql.domain` 等于实际 `DOMAIN_ID`；
- `sql.query_id` 非空；
- `trace_id` 与请求头一致；
- 返回的 SQL 使用真实登记字段；
- 不要求模型生成 `tenant_id`，租户条件由服务端参数化注入。

## 8. 失败排查

- `表 orders 未登记列白名单`：重新确认 columns 请求成功，并重新 publish。
- `Unknown column`：重新执行 `introspect`，核对实际时间字段，不要登记模型猜出的字段。
- `没有符合条件的数据`：检查认证用户的 `tenant_id` 是否有测试数据，以及查询时间范围。
- `服务暂时不可用`：用错误响应的 `trace_id` 查服务端日志。

## 9. 删除测试域

测试完成后，建议使用 [domain-cleanup.md](domain-cleanup.md) 的删除接口清理测试元数据。删除真实业务表不属于 Schema Registry 的职责。
