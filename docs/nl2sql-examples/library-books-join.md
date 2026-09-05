# 图书 JOIN

## 0. 建表、测试数据和只读权限

仅在测试数据库执行：

```sql
CREATE TABLE IF NOT EXISTS book_authors (
    tenant_id VARCHAR(64) NOT NULL,
    author_id VARCHAR(64) NOT NULL,
    author_name VARCHAR(128) NOT NULL,
    country VARCHAR(64) NOT NULL,
    PRIMARY KEY (tenant_id, author_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS books (
    tenant_id VARCHAR(64) NOT NULL,
    book_id VARCHAR(64) NOT NULL,
    title VARCHAR(255) NOT NULL,
    price DECIMAL(10,2) NOT NULL,
    published_year INT NOT NULL,
    author_id VARCHAR(64) NOT NULL,
    created_at DATETIME NOT NULL,
    PRIMARY KEY (tenant_id, book_id),
    KEY idx_books_tenant_created (tenant_id, created_at, book_id),
    KEY idx_books_tenant_author (tenant_id, author_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

INSERT INTO book_authors (tenant_id, author_id, author_name, country) VALUES
    ('<TENANT_ID>', 'A01', '刘慈欣', '中国'),
    ('<TENANT_ID>', 'A02', 'J.K.罗琳', '英国')
ON DUPLICATE KEY UPDATE
    author_name = VALUES(author_name),
    country = VALUES(country);

INSERT INTO books
    (tenant_id, book_id, title, price, published_year, author_id, created_at)
VALUES
    ('<TENANT_ID>', 'B001', '三体', 68.00, 2008, 'A01', '2026-09-01 09:00:00'),
    ('<TENANT_ID>', 'B002', '哈利·波特与魔法石', 45.00, 1997, 'A02', '2026-09-02 10:30:00')
ON DUPLICATE KEY UPDATE
    title = VALUES(title),
    price = VALUES(price),
    published_year = VALUES(published_year),
    author_id = VALUES(author_id),
    created_at = VALUES(created_at);

GRANT SELECT ON <DB_NAME>.books TO 'nl2sql_readonly'@'%';
GRANT SELECT ON <DB_NAME>.book_authors TO 'nl2sql_readonly'@'%';
FLUSH PRIVILEGES;
SHOW GRANTS FOR 'nl2sql_readonly'@'%';
```

把 `<TENANT_ID>` 替换为认证用户所属租户。生产库只执行 `GRANT SELECT`。

## 1. 确认表和字段

```sql
SHOW CREATE TABLE books;
SHOW CREATE TABLE book_authors;
```

```http
POST /admin/schema/domains/<DOMAIN_ID>/introspect
Authorization: Bearer <SCHEMA_ADMIN_TOKEN>
Content-Type: application/json

{
  "tables": ["books", "book_authors"],
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
  "name": "library",
  "description": "书籍和作者",
  "keywords": ["书籍", "作者", "图书"]
}
```

保存响应中的 `domain_id`。

## 3. 登记表

```http
POST /admin/schema/domains/<DOMAIN_ID>/tables
Authorization: Bearer <SCHEMA_ADMIN_TOKEN>
Content-Type: application/json

{"table":"books","description":"书籍表","required_tenant_filter":true}
```

```http
POST /admin/schema/domains/<DOMAIN_ID>/tables
Authorization: Bearer <SCHEMA_ADMIN_TOKEN>
Content-Type: application/json

{"table":"book_authors","description":"作者表","required_tenant_filter":true}
```

## 4. 登记列

```http
POST /admin/schema/domains/<DOMAIN_ID>/columns
Authorization: Bearer <SCHEMA_ADMIN_TOKEN>
Content-Type: application/json

{
  "table": "books",
  "columns": [
    {"column_name":"tenant_id","data_type":"varchar","selectable":false,"filterable":true,"sortable":false,"aggregatable":false,"sensitive":false},
    {"column_name":"book_id","data_type":"varchar","selectable":true,"filterable":true,"sortable":true,"aggregatable":false,"sensitive":false},
    {"column_name":"title","data_type":"varchar","selectable":true,"filterable":true,"sortable":true,"aggregatable":false,"sensitive":false},
    {"column_name":"price","data_type":"decimal","selectable":true,"filterable":true,"sortable":true,"aggregatable":true,"sensitive":false},
    {"column_name":"published_year","data_type":"int","selectable":true,"filterable":true,"sortable":true,"aggregatable":false,"sensitive":false},
    {"column_name":"author_id","data_type":"varchar","selectable":false,"filterable":true,"sortable":false,"aggregatable":false,"sensitive":false},
    {"column_name":"created_at","data_type":"datetime","selectable":true,"filterable":true,"sortable":true,"aggregatable":false,"sensitive":false}
  ]
}
```

```http
POST /admin/schema/domains/<DOMAIN_ID>/columns
Authorization: Bearer <SCHEMA_ADMIN_TOKEN>
Content-Type: application/json

{
  "table": "book_authors",
  "columns": [
    {"column_name":"tenant_id","data_type":"varchar","selectable":false,"filterable":true,"sortable":false,"aggregatable":false,"sensitive":false},
    {"column_name":"author_id","data_type":"varchar","selectable":false,"filterable":true,"sortable":false,"aggregatable":false,"sensitive":false},
    {"column_name":"author_name","data_type":"varchar","selectable":true,"filterable":true,"sortable":true,"aggregatable":false,"sensitive":false},
    {"column_name":"country","data_type":"varchar","selectable":true,"filterable":true,"sortable":true,"aggregatable":false,"sensitive":false}
  ]
}
```

## 5. 登记 JOIN

```http
POST /admin/schema/domains/<DOMAIN_ID>/joins
Authorization: Bearer <SCHEMA_ADMIN_TOKEN>
Content-Type: application/json

{
  "table": "books",
  "joins": [
    {"table":"book_authors","columns":{"author_id":"author_id"},"join_type":"LEFT"}
  ]
}
```

## 6. 发布

```http
POST /admin/schema/domains/<DOMAIN_ID>/publish
Authorization: Bearer <SCHEMA_ADMIN_TOKEN>
Content-Type: application/json

{"version":1,"comment":"发布图书 JOIN"}
```

只读权限已在第 0 步完成。

## 7. 查询

```http
POST /chat
Authorization: Bearer <ACCESS_TOKEN>
Content-Type: application/json

{
  "question": "列出书籍编号、书名、价格、作者姓名、国家和创建时间",
  "conversation_id": "library-001"
}
```

发送“下一页”继续，格式见 [pagination.md](pagination.md)。
