# NL2SQL 示例

## 顺序

1. [orders-single-table.md](orders-single-table.md)：单表注册与查询
2. [pagination.md](pagination.md)：分页查询
3. [customer-orders-join.md](customer-orders-join.md)：两表 JOIN
4. [library-books-join.md](library-books-join.md)：完整图书 JOIN
5. [row-policy.md](row-policy.md)：行级权限
6. [domain-cleanup.md](domain-cleanup.md)：删除数据域

## 变量

```text
BASE_URL=http://127.0.0.1:8000
SCHEMA_ADMIN_TOKEN=<schema:admin token>
ACCESS_TOKEN=<chat:ask token>
TENANT_ID=<tenant id>
DB_NAME=<database name>
DOMAIN_ID=<接口返回的 domain_id>
```

## 固定流程

```text
确认真实表和字段
→ 执行分页配置迁移
→ 创建数据域
→ introspect
→ 登记表
→ 登记列
→ 登记 JOIN/行权限
→ publish
→ GRANT SELECT
→ POST /chat
```

## 登记列参数

接口：

```http
POST /admin/schema/domains/<DOMAIN_ID>/columns
Authorization: Bearer <SCHEMA_ADMIN_TOKEN>
Content-Type: application/json
```

请求体：

```json
{
  "table": "orders",
  "columns": [
    {
      "column_name": "order_id",
      "data_type": "varchar",
      "business_name": "订单号",
      "description": "订单唯一编号",
      "selectable": true,
      "filterable": true,
      "sortable": true,
      "aggregatable": false,
      "sensitive": false,
      "masking_rule": null
    }
  ]
}
```

外层参数：

| 参数 | 必填 | 含义 |
|---|---|---|
| `table` | 是 | 已登记的数据表真实名称 |
| `columns` | 是 | 列对象数组，至少一项 |

列对象参数：

| 参数 | 必填 | 含义 |
|---|---|---|
| `column_name` | 是 | 数据库真实列名，必须与 `introspect` 返回值一致 |
| `data_type` | 是 | 数据库真实类型，如 `varchar`、`decimal`、`datetime` |
| `business_name` | 否 | 中文业务名称，只帮助模型理解，不会改数据库列名 |
| `description` | 否 | 列用途说明，只作为元数据提示 |
| `selectable` | 否，默认 `true` | 是否允许出现在 `SELECT` 输出中；租户字段、JOIN 键可设为 `false` |
| `filterable` | 否，默认 `true` | 是否允许用于 `WHERE` 和行权限条件；策略引用的列必须为 `true` |
| `sortable` | 否，默认 `false` | 是否允许用于排序；分页固定使用的列必须设为 `true` |
| `aggregatable` | 否，默认 `false` | 是否允许用于 `SUM`、`AVG` 等聚合；金额、数量列可设为 `true` |
| `sensitive` | 否，默认 `false` | 是否敏感字段；设为 `true` 后 SQL 不允许引用 |
| `masking_rule` | 否 | 脱敏规则名称元数据；不会自动执行脱敏 |

常用配置：

```json
{
  "column_name": "tenant_id",
  "data_type": "varchar",
  "selectable": false,
  "filterable": true,
  "sortable": false,
  "aggregatable": false,
  "sensitive": false
}
```

```json
{
  "column_name": "amount",
  "data_type": "decimal",
  "selectable": true,
  "filterable": true,
  "sortable": true,
  "aggregatable": true,
  "sensitive": false
}
```

```json
{
  "column_name": "password",
  "data_type": "varchar",
  "selectable": false,
  "filterable": false,
  "sortable": false,
  "aggregatable": false,
  "sensitive": true
}
```

分页示例还必须登记：

```json
{
  "column_name": "created_at",
  "data_type": "datetime",
  "selectable": true,
  "filterable": true,
  "sortable": true,
  "aggregatable": false,
  "sensitive": false
}
```

```json
{
  "column_name": "order_id",
  "data_type": "varchar",
  "selectable": true,
  "filterable": true,
  "sortable": true,
  "aggregatable": false,
  "sensitive": false
}
```

`domain_id`、表名和列名必须使用接口或数据库返回的真实值。`publish` 不会自动授予数据库权限。租户条件由服务端注入，不能在问题中指定 `tenant_id`。
