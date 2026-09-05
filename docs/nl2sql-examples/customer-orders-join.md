# 订单与客户 JOIN

## 0. 建表、测试数据和只读权限

仅在测试数据库执行：

```sql
-- 创建消费者表
CREATE TABLE consumer (
    tenant_id VARCHAR(50) NOT NULL COMMENT '租户ID',
    consumer_id INT PRIMARY KEY AUTO_INCREMENT COMMENT '消费者ID',
    name VARCHAR(100) NOT NULL COMMENT '消费者姓名',
    email VARCHAR(100) UNIQUE COMMENT '电子邮箱',
    phone VARCHAR(20) COMMENT '电话号码',
    address TEXT COMMENT '地址',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间'
);

-- 创建订单表
CREATE TABLE orders (
    tenant_id VARCHAR(50) NOT NULL COMMENT '租户ID',
    order_id INT PRIMARY KEY AUTO_INCREMENT COMMENT '订单ID',
    consumer_id INT COMMENT '消费者ID，用于关联consumer表',
    order_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '订单创建时间',
    total_amount DECIMAL(10, 2) COMMENT '订单总金额',
    status VARCHAR(20) DEFAULT 'pending' COMMENT '订单状态',
    shipping_address TEXT COMMENT '配送地址',
    notes TEXT COMMENT '订单备注'
);

-- 添加索引以提高查询性能
CREATE INDEX idx_orders_tenant_id ON orders(tenant_id);
CREATE INDEX idx_orders_consumer_id ON orders(consumer_id);
CREATE INDEX idx_orders_order_date ON orders(order_date);

-- 插入消费者数据
INSERT INTO consumer (tenant_id, name, email, phone, address) VALUES
('tenant-test', '张三', 'zhangsan@example.com', '13800138001', '北京市朝阳区建国路88号'),
('tenant-test', '李四', 'lisi@example.com', '13800138002', '上海市浦东新区世纪大道100号'),
('tenant-test', '王五', 'wangwu@example.com', '13800138003', '广州市天河区珠江路200号'),
('tenant-test', '赵六', 'zhaoliu@example.com', '13800138004', '深圳市南山区科技园300号'),
('tenant-test', '钱七', 'qianqi@example.com', '13800138005', '杭州市西湖区文一街400号'),
('tenant-test', '孙八', 'sunba@example.com', '13800138006', '成都市高新区天府大道500号'),
('tenant-test', '周九', 'zhoujiu@example.com', '13800138007', '武汉市江汉区解放大道600号'),
('tenant-test', '吴十', 'wushi@example.com', '13800138008', '南京市鼓楼区中山路700号'),
('tenant-test', '郑十一', 'zheng11@example.com', '13800138009', '西安市雁塔区高新路800号'),
('tenant-test', '王十二', 'wang12@example.com', '13800138010', '重庆市渝北区洪湖路900号');

-- 插入订单数据
INSERT INTO orders (tenant_id, consumer_id, order_date, total_amount, status, shipping_address, notes) VALUES
-- 张三的订单 (consumer_id = 1)
('tenant-test', 1, '2023-01-15 10:30:00', 299.99, 'completed', '北京市朝阳区建国路88号', '工作日配送'),
('tenant-test', 1, '2023-02-20 14:45:00', 159.50, 'shipped', '北京市朝阳区建国路88号', '请放在前台'),
('tenant-test', 1, '2023-03-10 09:15:00', 89.99, 'pending', '北京市朝阳区建国路88号', ''),

-- 李四的订单 (consumer_id = 2)
('tenant-test', 2, '2023-01-18 11:20:00', 459.00, 'completed', '上海市浦东新区世纪大道100号', ''),
('tenant-test', 2, '2023-02-25 16:30:00', 279.90, 'delivered', '上海市浦东新区世纪大道100号', '周末配送'),
('tenant-test', 2, '2023-03-12 13:10:00', 199.99, 'processing', '上海市浦东新区世纪大道100号', ''),

-- 王五的订单 (consumer_id = 3)
('tenant-test', 3, '2023-01-22 08:45:00', 350.00, 'completed', '广州市天河区珠江路200号', ''),
('tenant-test', 3, '2023-03-05 15:20:00', 129.99, 'shipped', '广州市天河区珠江路200号', '请送到办公室'),
('tenant-test', 3, '2023-03-15 10:00:00', 79.50, 'pending', '广州市天河区珠江路200号', ''),

-- 赵六的订单 (consumer_id = 4)
('tenant-test', 4, '2023-02-01 12:30:00', 599.99, 'completed', '深圳市南山区科技园300号', ''),
('tenant-test', 4, '2023-02-28 17:40:00', 329.50, 'delivered', '深圳市南山区科技园300号', ''),
('tenant-test', 4, '2023-03-18 09:50:00', 199.00, 'processing', '深圳市南山区科技园300号', ''),

-- 钱七的订单 (consumer_id = 5)
('tenant-test', 5, '2023-02-05 13:15:00', 429.00, 'completed', '杭州市西湖区文一街400号', ''),
('tenant-test', 5, '2023-03-08 11:30:00', 189.99, 'shipped', '杭州市西湖区文一街400号', '请放在门口'),
('tenant-test', 5, '2023-03-20 14:20:00', 99.50, 'pending', '杭州市西湖区文一街400号', ''),

-- 孙八的订单 (consumer_id = 6)
('tenant-test', 6, '2023-02-10 16:45:00', 379.99, 'completed', '成都市高新区天府大道500号', ''),
('tenant-test', 6, '2023-03-12 10:15:00', 159.50, 'delivered', '成都市高新区天府大道500号', ''),
('tenant-test', 6, '2023-03-22 11:40:00', 129.00, 'processing', '成都市高新区天府大道500号', ''),

-- 周九的订单 (consumer_id = 7)
('tenant-test', 7, '2023-02-15 09:30:00', 499.00, 'completed', '武汉市江汉区解放大道600号', ''),
('tenant-test', 7, '2023-03-15 14:50:00', 229.99, 'shipped', '武汉市江汉区解放大道600号', ''),
('tenant-test', 7, '2023-03-24 10:10:00', 159.50, 'pending', '武汉市江汉区解放大道600号', ''),

-- 吴十的订单 (consumer_id = 8)
('tenant-test', 8, '2023-02-20 11:20:00', 359.99, 'completed', '南京市鼓楼区中山路700号', ''),
('tenant-test', 8, '2023-03-18 15:30:00', 189.00, 'delivered', '南京市鼓楼区中山路700号', '请送到前台'),
('tenant-test', 8, '2023-03-26 09:40:00', 99.99, 'processing', '南京市鼓楼区中山路700号', ''),

-- 郑十一的订单 (consumer_id = 9)
('tenant-test', 9, '2023-02-25 12:40:00', 479.50, 'completed', '西安市雁塔区高新路800号', ''),
('tenant-test', 9, '2023-03-20 10:25:00', 259.99, 'shipped', '西安市雁塔区高新路800号', '周末配送'),
('tenant-test', 9, '2023-03-28 13:15:00', 139.00, 'pending', '西安市雁塔区高新路800号', ''),

-- 王十二的订单 (consumer_id = 10)
('tenant-test', 10, '2023-03-01 15:10:00', 429.99, 'completed', '重庆市渝北区洪湖路900号', ''),
('tenant-test', 10, '2023-03-22 11:45:00', 199.50, 'delivered', '重庆市渝北区洪湖路900号', ''),
('tenant-test', 10, '2023-03-30 08:30:00', 79.99, 'processing', '重庆市渝北区洪湖路900号', '');

GRANT SELECT ON <DB_NAME>.orders TO 'nl2sql_readonly'@'%';
GRANT SELECT ON <DB_NAME>.consumer TO 'nl2sql_readonly'@'%';
FLUSH PRIVILEGES;
SHOW GRANTS FOR 'nl2sql_readonly'@'%';
```

把 `<TENANT_ID>` 替换为认证用户所属租户。生产库只执行 `GRANT SELECT`。

## 1. 确认表和字段

```sql
SHOW CREATE TABLE orders;
SHOW CREATE TABLE consumer;
```

```http
POST /admin/schema/domains/<DOMAIN_ID>/introspect
Authorization: Bearer <SCHEMA_ADMIN_TOKEN>
Content-Type: application/json

{
  "tables": ["orders", "consumer"],
  "include_columns": true
}
```

以返回的字段为准，列登记不要写不存在的字段。

## 2. 创建数据域

```http
POST /admin/schema/domains
Authorization: Bearer <SCHEMA_ADMIN_TOKEN>
Content-Type: application/json

{
  "name": "customer_orders",
  "description": "订单和消费者",
  "keywords": ["订单客户", "客户订单", "消费者"]
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
  "table": "consumer",
  "description": "消费者表",
  "required_tenant_filter": true
}
```

## 4. 登记列

```http
POST /admin/schema/domains/<DOMAIN_ID>/columns
Authorization: Bearer <SCHEMA_ADMIN_TOKEN>
Content-Type: application/json

{
  "table": "orders",
  "columns": [
    {"column_name":"tenant_id","data_type":"varchar","selectable":false,"filterable":true,"sortable":false,"aggregatable":false,"sensitive":false},
    {"column_name":"order_id","data_type":"int","selectable":true,"filterable":true,"sortable":true,"aggregatable":false,"sensitive":false},
    {"column_name":"consumer_id","data_type":"int","selectable":false,"filterable":true,"sortable":false,"aggregatable":false,"sensitive":false},
    {"column_name":"order_date","data_type":"timestamp","selectable":true,"filterable":true,"sortable":true,"aggregatable":false,"sensitive":false},
    {"column_name":"total_amount","data_type":"decimal","selectable":true,"filterable":true,"sortable":true,"aggregatable":true,"sensitive":false},
    {"column_name":"status","data_type":"varchar","selectable":true,"filterable":true,"sortable":false,"aggregatable":false,"sensitive":false},
    {"column_name":"shipping_address","data_type":"text","selectable":false,"filterable":false,"sortable":false,"aggregatable":false,"sensitive":false},
    {"column_name":"notes","data_type":"text","selectable":false,"filterable":false,"sortable":false,"aggregatable":false,"sensitive":false}
  ]
}
```

```http
POST /admin/schema/domains/<DOMAIN_ID>/columns
Authorization: Bearer <SCHEMA_ADMIN_TOKEN>
Content-Type: application/json

{
  "table": "consumer",
  "columns": [
    {"column_name":"tenant_id","data_type":"varchar","selectable":false,"filterable":true,"sortable":false,"aggregatable":false,"sensitive":false},
    {"column_name":"consumer_id","data_type":"int","selectable":true,"filterable":true,"sortable":true,"aggregatable":false,"sensitive":false},
    {"column_name":"name","data_type":"varchar","selectable":true,"filterable":true,"sortable":true,"aggregatable":false,"sensitive":false},
    {"column_name":"email","data_type":"varchar","selectable":false,"filterable":true,"sortable":false,"aggregatable":false,"sensitive":true},
    {"column_name":"phone","data_type":"varchar","selectable":false,"filterable":false,"sortable":false,"aggregatable":false,"sensitive":true},
    {"column_name":"address","data_type":"text","selectable":false,"filterable":false,"sortable":false,"aggregatable":false,"sensitive":true},
    {"column_name":"created_at","data_type":"timestamp","selectable":true,"filterable":true,"sortable":true,"aggregatable":false,"sensitive":false}
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
    {"table":"consumer","columns":{"consumer_id":"consumer_id"},"join_type":"LEFT"}
  ]
}
```

## 6. 发布

```http
POST /admin/schema/domains/<DOMAIN_ID>/publish
Authorization: Bearer <SCHEMA_ADMIN_TOKEN>
Content-Type: application/json

{"version":1,"comment":"发布订单消费者 JOIN"}
```

只读权限已在第 0 步完成。

## 7. 查询

```http
POST /chat
Authorization: Bearer <ACCESS_TOKEN>
Content-Type: application/json

{
  "question": "查询本月订单号、订单日期、金额和消费者姓名",
  "conversation_id": "customer-orders-001"
}
```

发送“下一页”继续，格式见 [pagination.md](pagination.md)。
