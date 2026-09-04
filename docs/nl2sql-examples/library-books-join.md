# books × book_authors 完整 JOIN 示例

这是一个完整的两表示例。只有在你的数据库确实存在下列两张表和字段时，才能按本示例执行。

## 业务表前提

```sql
USE <DB_NAME>;

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
    PRIMARY KEY (tenant_id, book_id),
    KEY idx_books_tenant_author (tenant_id, author_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

如果表已存在，不要执行假设性的 DDL；先执行：

```sql
SHOW CREATE TABLE books;
SHOW CREATE TABLE book_authors;
```

确认实际字段与本示例一致。

## 1. 插入测试数据（可选）

仅在测试库执行，并确认租户值与认证用户一致：

```sql
INSERT INTO book_authors
    (tenant_id, author_id, author_name, country)
VALUES
    ('<TENANT_ID>', 'A01', '刘慈欣', '中国'),
    ('<TENANT_ID>', 'A02', 'J.K.罗琳', '英国')
ON DUPLICATE KEY UPDATE
    author_name = VALUES(author_name),
    country = VALUES(country);

INSERT INTO books
    (tenant_id, book_id, title, price, published_year, author_id)
VALUES
    ('<TENANT_ID>', 'B001', '三体', 68.00, 2008, 'A01'),
    ('<TENANT_ID>', 'B002', '哈利·波特与魔法石', 45.00, 1997, 'A02')
ON DUPLICATE KEY UPDATE
    title = VALUES(title),
    price = VALUES(price),
    published_year = VALUES(published_year),
    author_id = VALUES(author_id);
```

## 2. 授权只读账号

```sql
GRANT SELECT ON <DB_NAME>.books TO 'nl2sql_readonly'@'%';
GRANT SELECT ON <DB_NAME>.book_authors TO 'nl2sql_readonly'@'%';
FLUSH PRIVILEGES;
SHOW GRANTS FOR 'nl2sql_readonly'@'%';
```

## 3. 创建数据域

```http
POST /admin/schema/domains
Authorization: Bearer <SCHEMA_ADMIN_TOKEN>
Content-Type: application/json

{
  "name": "library",
  "description": "书籍和作者数据，通过 books.author_id 关联 book_authors.author_id",
  "keywords": ["书籍", "作者", "图书", "书名", "作家"]
}
```

本示例预期返回 `domain_id=library`，但实际操作仍必须以响应为准。

## 4. 探测结构

```http
POST /admin/schema/domains/<DOMAIN_ID>/introspect
Authorization: Bearer <SCHEMA_ADMIN_TOKEN>
Content-Type: application/json

{
  "tables": ["books", "book_authors"],
  "include_columns": true
}
```

必须确认实际返回以下字段：

```text
books: tenant_id, book_id, title, price, published_year, author_id
book_authors: tenant_id, author_id, author_name, country
```

如果实际结构不同，按实际返回改写后续 JSON，不能照抄。

## 5. 登记两张表

```http
POST /admin/schema/domains/<DOMAIN_ID>/tables
Authorization: Bearer <SCHEMA_ADMIN_TOKEN>
Content-Type: application/json

{
  "table": "books",
  "description": "书籍主表，author_id 仅用于关联作者",
  "required_tenant_filter": true
}
```

```http
POST /admin/schema/domains/<DOMAIN_ID>/tables
Authorization: Bearer <SCHEMA_ADMIN_TOKEN>
Content-Type: application/json

{
  "table": "book_authors",
  "description": "作者信息表，author_id 为作者编号",
  "required_tenant_filter": true
}
```

## 6. 登记完整列白名单

启用列白名单后，两张被 JOIN 的物理表都必须有列登记。JOIN 键不需要输出，因此可以 `selectable=false`；但必须保留在白名单中。

### books

```http
POST /admin/schema/domains/<DOMAIN_ID>/columns
Authorization: Bearer <SCHEMA_ADMIN_TOKEN>
Content-Type: application/json

{
  "table": "books",
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
      "column_name": "book_id",
      "data_type": "varchar",
      "business_name": "书籍编号",
      "description": "书籍唯一编号",
      "selectable": true,
      "filterable": true,
      "sortable": true,
      "aggregatable": false,
      "sensitive": false
    },
    {
      "column_name": "title",
      "data_type": "varchar",
      "business_name": "书名",
      "description": "书籍名称",
      "selectable": true,
      "filterable": true,
      "sortable": true,
      "aggregatable": false,
      "sensitive": false
    },
    {
      "column_name": "price",
      "data_type": "decimal",
      "business_name": "价格",
      "description": "书籍价格",
      "selectable": true,
      "filterable": true,
      "sortable": true,
      "aggregatable": true,
      "sensitive": false
    },
    {
      "column_name": "published_year",
      "data_type": "int",
      "business_name": "出版年份",
      "description": "书籍出版年份",
      "selectable": true,
      "filterable": true,
      "sortable": true,
      "aggregatable": false,
      "sensitive": false
    },
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
  ]
}
```

### book_authors

```http
POST /admin/schema/domains/<DOMAIN_ID>/columns
Authorization: Bearer <SCHEMA_ADMIN_TOKEN>
Content-Type: application/json

{
  "table": "book_authors",
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
      "column_name": "author_id",
      "data_type": "varchar",
      "business_name": "作者编号",
      "description": "仅用于 JOIN",
      "selectable": false,
      "filterable": true,
      "sortable": false,
      "aggregatable": false,
      "sensitive": false
    },
    {
      "column_name": "author_name",
      "data_type": "varchar",
      "business_name": "作者姓名",
      "description": "作者名称",
      "selectable": true,
      "filterable": true,
      "sortable": true,
      "aggregatable": false,
      "sensitive": false
    },
    {
      "column_name": "country",
      "data_type": "varchar",
      "business_name": "国家",
      "description": "作者所属国家",
      "selectable": true,
      "filterable": true,
      "sortable": true,
      "aggregatable": false,
      "sensitive": false
    }
  ]
}
```

`tenant_id` 不能标记为 `sensitive=true`。如果行权限模板引用 `tenant_id`，还必须是 `filterable=true`。

## 7. 登记 JOIN

```http
POST /admin/schema/domains/<DOMAIN_ID>/joins
Authorization: Bearer <SCHEMA_ADMIN_TOKEN>
Content-Type: application/json

{
  "table": "books",
  "joins": [
    {
      "table": "book_authors",
      "columns": {
        "author_id": "author_id"
      },
      "join_type": "LEFT"
    }
  ]
}
```

对应业务结构：

```sql
LEFT JOIN book_authors AS a
  ON books.author_id = a.author_id
```

## 8. 检查 JOIN 并发布

```http
GET /admin/schema/domains/<DOMAIN_ID>/joins
Authorization: Bearer <SCHEMA_ADMIN_TOKEN>
```

```http
POST /admin/schema/domains/<DOMAIN_ID>/publish
Authorization: Bearer <SCHEMA_ADMIN_TOKEN>
Content-Type: application/json

{
  "version": 1,
  "comment": "发布书籍作者关联关系"
}
```

## 9. 可选配置行权限

行权限不是租户条件的替代品。服务端始终从认证上下文注入租户条件。需要额外按用户/角色/部门限制行时，参阅 [row-policy.md](row-policy.md)。

## 10. 验证 JOIN 问答

```http
POST /chat
Authorization: Bearer <ACCESS_TOKEN>
Content-Type: application/json
X-Trace-Id: library-books-join-001

{
  "question": "列出书名、价格、作者姓名和国家",
  "conversation_id": "library-books-join-001"
}
```

模型候选 SQL 的业务结构应类似：

```sql
SELECT b.title, b.price, a.author_name, a.country
FROM books AS b
LEFT JOIN book_authors AS a
  ON b.author_id = a.author_id
```

这只是业务结构示意，不要求空格、别名完全一致，也不应出现模型硬编码的 `tenant_id`。服务端会对每张物理表进行参数化租户策略重写。

验证 `mode=nl2sql`、`status=answered`、`sql.columns`、`sql.query_id`、`trace_id` 和实际返回数据。

## 11. 失败排查

- `表 books 引用了未授权字段: author_id`：确认 `books.author_id` 已登记，且没有把 JOIN 键从白名单删除。
- `表 xxx 未登记列白名单`：确认 JOIN 两张表都成功调用 columns，并重新 publish。
- `Unknown column`：以 introspect/SHOW CREATE TABLE 为准修改字段，不要登记不存在的 `create_time`。
- `没有符合条件的数据`：确认测试数据的 `tenant_id` 与认证用户一致。
- `INFRASTRUCTURE_ERROR`：按响应 `trace_id` 查询服务端日志。
