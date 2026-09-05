# 订单与客户 JOIN

## 0. 建表、测试数据和只读权限

仅在测试数据库执行：

```sql
CREATE TABLE IF NOT EXISTS orders (
    tenant_id VARCHAR(64) NOT NULL,
    order_id VARCHAR(64) NOT NULL,
    customer_id VARCHAR(64) NOT NULL,
    amount DECIMAL(12,2) NOT NULL,
    created_at DATETIME NOT NULL,
    PRIMARY KEY (tenant_id, order_id),
    KEY idx_orders_tenant_created (tenant_id, created_at, order_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS order_customers (
    tenant_id VARCHAR(64) NOT NULL,
    customer_id VARCHAR(64) NOT NULL,
    customer_name VARCHAR(128) NOT NULL,
    PRIMARY KEY (tenant_id, customer_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

INSERT INTO order_customers (tenant_id, customer_id, customer_name) VALUES
    ('<TENANT_ID>', 'C001', '张三'),
    ('<TENANT_ID>', 'C002', '李四')
ON DUPLICATE KEY UPDATE customer_name = VALUES(customer_name);

INSERT INTO orders (tenant_id, order_id, customer_id, amount, created_at) VALUES
    ('<TENANT_ID>', 'O001', 'C001', 128.50, '2026-09-01 09:00:00'),
    ('<TENANT_ID>', 'O002', 'C002', 256.00, '2026-09-02 10:30:00')
ON DUPLICATE KEY UPDATE
    customer_id = VALUES(customer_id),
    amount = VALUES(amount),
    created_at = VALUES(created_at);

GRANT SELECT ON <DB_NAME>.orders TO 'nl2sql_readonly'@'%';
GRANT SELECT ON <DB_NAME>.order_customers TO 'nl2sql_readonly'@'%';
FLUSH PRIVILEGES;
SHOW GRANTS FOR 'nl2sql_readonly'@'%';
```

把 `<TENANT_ID>` 替换为认证用户所属租户。生产库只执行 `GRANT SELECT`。

## 1. 确认表和字段

```sql
SHOW CREATE TABLE orders;
SHOW CREATE TABLE order_customers;
```

## 2. 创建数据域

```http
POST /admin/schema/domains
Authorization: Bearer <SCHEMA_ADMIN_TOKEN>
Content-Type: application/json

{
  "name": "customer_orders",
  "description": "订单和客户",
  "keywords": ["订单客户", "客户订单"]
}
```

保存响应中的 `domain_id`。

## 3. 登记表

```http
POST /admin/schema/domains/<DOMAIN_ID>/tables
Authorization: Bearer <SCHEMA_ADMIN_TOKEN>
Content-Type: application/json

{
  "table": "orders",
  "description": "订单表",
  "required_tenant_filter": true
}
```

```http
POST /admin/schema/domains/<DOMAIN_ID>/tables
Authorization: Bearer <SCHEMA_ADMIN_TOKEN>
Content-Type: application/json

{
  "table": "order_customers",
  "description": "客户表",
  "required_tenant_filter": true
}
```

## 4. 登记列

两张表被 SQL 引用的列都要登记，JOIN 键不能省略。

```http
POST /admin/schema/domains/<DOMAIN_ID>/columns
Authorization: Bearer <SCHEMA_ADMIN_TOKEN>
Content-Type: application/json

{
  "table": "orders",
  "columns": [
    {"column_name":"tenant_id","data_type":"varchar","selectable":false,"filterable":true,"sortable":false,"aggregatable":false,"sensitive":false},
    {"column_name":"customer_id","data_type":"varchar","selectable":false,"filterable":true,"sortable":false,"aggregatable":false,"sensitive":false},
    {"column_name":"amount","data_type":"decimal","selectable":true,"filterable":true,"sortable":true,"aggregatable":true,"sensitive":false},
    {"column_name":"created_at","data_type":"datetime","selectable":true,"filterable":true,"sortable":true,"aggregatable":false,"sensitive":false},
    {"column_name":"order_id","data_type":"varchar","selectable":true,"filterable":true,"sortable":true,"aggregatable":false,"sensitive":false}
  ]
}
```

```http
POST /admin/schema/domains/<DOMAIN_ID>/columns
Authorization: Bearer <SCHEMA_ADMIN_TOKEN>
Content-Type: application/json

{
  "table": "order_customers",
  "columns": [
    {"column_name":"tenant_id","data_type":"varchar","selectable":false,"filterable":true,"sortable":false,"aggregatable":false,"sensitive":false},
    {"column_name":"customer_id","data_type":"varchar","selectable":false,"filterable":true,"sortable":false,"aggregatable":false,"sensitive":false},
    {"column_name":"customer_name","data_type":"varchar","selectable":true,"filterable":true,"sortable":true,"aggregatable":false,"sensitive":false}
  ]
}
```

## 5. 登记 JOIN

```http
POST /admin/schema/domains/<DOMAIN_ID>/joins
Authorization: Bearer <SCHEMA_ADMIN_TOKEN>
Content-Type: application/json

{
  "table": "orders",
  "joins": [
    {"table":"order_customers","columns":{"customer_id":"customer_id"},"join_type":"LEFT"}
  ]
}
```

## 6. 发布

```http
POST /admin/schema/domains/<DOMAIN_ID>/publish
Authorization: Bearer <SCHEMA_ADMIN_TOKEN>
Content-Type: application/json

{"version":1,"comment":"发布订单客户 JOIN"}
```

只读权限已在第 0 步完成。

## 7. 查询

```http
POST /chat
Authorization: Bearer <ACCESS_TOKEN>
Content-Type: application/json

{
  "question": "查询本月订单及客户名称",
  "conversation_id": "customer-orders-001"
}
```

发送“下一页”继续，格式见 [pagination.md](pagination.md)。租户条件由服务端注入。
