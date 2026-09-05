# NL2SQL 分页

先完成 [orders-single-table.md](orders-single-table.md) 的注册、列登记和发布。

## 首页

前端正常发送查询，不传分页字段：

```http
POST /chat
Authorization: Bearer <ACCESS_TOKEN>
Content-Type: application/json

{
  "question": "列出最近的订单",
  "conversation_id": "orders-page"
}
```

后端固定每页返回 5 条，并在服务端保存分页位置。响应只返回：

```json
{
  "sql": {
    "row_count": 5,
    "truncated": true
  }
}
```

`truncated=true` 表示还有下一页。回答末尾也会提示“还有下一页”或“已经是最后一页”。

## 下一页

前端只发送自然语言“下一页”，不传 `cursor`、`page_size`、SQL 或排序值：

```http
POST /chat
Authorization: Bearer <ACCESS_TOKEN>
Content-Type: application/json

{
  "question": "下一页",
  "conversation_id": "orders-page"
}
```

后端根据 `tenant_id + user_id + conversation_id` 读取服务端分页状态，复用已校验的 SQL，不重新调用 LLM。重复发送“下一页”，直到响应中的 `sql.truncated` 为 `false`。

## 上一页

前端只发送：

```http
POST /chat
Authorization: Bearer <ACCESS_TOKEN>
Content-Type: application/json

{
  "question": "上一页",
  "conversation_id": "orders-page"
}
```

后端从服务端保存的分页历史回到上一页。第一页没有上一页时，返回当前页并提示不能继续向前翻。

分页状态保存在会话状态存储中，不保存在前端。分页使用固定排序：

```text
created_at DESC, order_id DESC
```

目标表必须登记这些排序列。JOIN 查询还必须使用已配置的分页主表排序列，并将排序列列入查询结果；否则后端无法生成下一页位置，不启用分页。聚合、UNION 或不支持固定排序的查询不启用分页。
