# 订单与客户 JOIN 流程

本示例演示两张真实表的受控 JOIN。示例使用 `orders` 和 `order_customers` 作为名称；如果你的真实表名不同，必须在全文统一替换，不能混用 `customer_orders`、`order_customers` 等名称。

## 执行前检查

```sql
SHOW CREATE TABLE orders;
SHOW CREATE TABLE order_customers;
```

确认：

- 两张表都真实存在；
- 两张表都登记到同一个数据域；
- JOIN 两侧字段真实存在；
- 两张表均有 `tenant_id`；
- 只读账号之后会分别获得两张表的 `SELECT` 权限。

## 1. 创建数据域并保存 ID

```http
POST /admin/schema/domains
Authorization: Bearer <SCHEMA_ADMIN_TOKEN>
Content-Type: application/json

{
  "name": "customer_orders",
  "description": "订单及客户信息",
  "keywords": ["订单客户", "客户订单", "customer orders"]
}
```

从响应读取 `domain_id`，例如 `customer_orders`。后续 `<DOMAIN_ID>` 必须全部替换成响应中的原值。

## 2. 探测两张表

```http
POST /admin/schema/domains/<DOMAIN_ID>/introspect
Authorization: Bearer <SCHEMA_ADMIN_TOKEN>
Content-Type: application/json

{
  "tables": ["orders", "order_customers"],
  "include_columns": true
}
```

仅把实际返回的字段用于后续 columns 请求。introspect 不会自动登记字段，也不会自动发布域。

## 3. 先登记两张表

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

```http
POST /admin/schema/domains/<DOMAIN_ID>/tables
Authorization: Bearer <SCHEMA_ADMIN_TOKEN>
Content-Type: application/json

{
  "table": "order_customers",
  "description": "客户信息表",
  "required_tenant_filter": true
}
```

必须两张表都成功登记后，再登记列。`sql_allowed_columns` 对所属表有外键约束。

## 4. 登记列白名单

以下只展示 JOIN 相关字段和输出字段。实际使用时，应把查询会引用的全部字段登记进去。

### orders

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
      "column_name": "customer_id",
      "data_type": "varchar",
      "business_name": "客户编号",
      "description": "仅用于 JOIN",
      "selectable": false,
      "filterable": true,
      "sortable": false,
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
    }
  ]
}
```

### order_customers

```http
POST /admin/schema/domains/<DOMAIN_ID>/columns
Authorization: Bearer <SCHEMA_ADMIN_TOKEN>
Content-Type: application/json

{
  "table": "order_customers",
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
      "column_name": "customer_id",
      "data_type": "varchar",
      "business_name": "客户编号",
      "description": "仅用于 JOIN",
      "selectable": false,
      "filterable": true,
      "sortable": false,
      "aggregatable": false,
      "sensitive": false
    },
    {
      "column_name": "customer_name",
      "data_type": "varchar",
      "business_name": "客户名称",
      "description": "客户名称",
      "selectable": true,
      "filterable": true,
      "sortable": true,
      "aggregatable": false,
      "sensitive": false
    }
  ]
}
```

JOIN 键可以 `selectable=false`，但不能从列白名单中省略；它必须能够参与关联。

## 5. 登记 JOIN

```http
POST /admin/schema/domains/<DOMAIN_ID>/joins
Authorization: Bearer <SCHEMA_ADMIN_TOKEN>
Content-Type: application/json

{
  "table": "orders",
  "joins": [
    {
      "table": "order_customers",
      "columns": {
        "customer_id": "customer_id"
      },
      "join_type": "LEFT"
    }
  ]
}
```

含义等价于：

```sql
LEFT JOIN order_customers
  ON orders.customer_id = order_customers.customer_id
```

JOIN 配置只会先写入草稿元数据，必须 publish 后才会被 NL2SQL 读取。

## 6. 检查 JOIN

```http
GET /admin/schema/domains/<DOMAIN_ID>/joins
Authorization: Bearer <SCHEMA_ADMIN_TOKEN>
```

检查返回的源表、目标表、列映射和 JOIN 类型都与登记请求一致。

## 7. 发布并授权

```http
POST /admin/schema/domains/<DOMAIN_ID>/publish
Authorization: Bearer <SCHEMA_ADMIN_TOKEN>
Content-Type: application/json

{
  "version": 1,
  "comment": "发布订单客户关联关系"
}
```

```sql
GRANT SELECT ON <DB_NAME>.orders TO 'nl2sql_readonly'@'%';
GRANT SELECT ON <DB_NAME>.order_customers TO 'nl2sql_readonly'@'%';
FLUSH PRIVILEGES;
```

## 8. 验证问答

```http
POST /chat
Authorization: Bearer <ACCESS_TOKEN>
Content-Type: application/json
X-Trace-Id: customer-orders-join-001

{
  "question": "查询本月订单及对应客户名称",
  "conversation_id": "customer-orders-join-001"
}
```

预期验证点：`mode=nl2sql`、`status=answered`、SQL 的两张表都在允许表中、JOIN 两侧字段都在列白名单中、`trace_id` 可在日志中检索。

LLM 不应生成 `tenant_id` 条件；服务端会对每张物理表注入参数化租户策略。若配置了行权限，当前 AST 重写支持 JOIN，并逐表应用策略；重写失败则拒绝执行。

## 9. 常见失败

- 外键失败：先登记两张表，再登记列。
- `表 xxx 未登记列白名单`：两张被引用的表都必须有列登记，再重新发布。
- JOIN 键未授权：检查两侧 `customer_id` 是否登记，且名称与真实字段完全一致。
- 查询无数据：检查两张表的 `tenant_id` 数据是否一致，以及只读账号权限。
