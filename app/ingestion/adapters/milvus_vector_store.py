"""Milvus 适配器（实现摄入存储相关端口），仅负责 dense 向量检索。"""
import json
from collections.abc import Iterable
from typing import Any

from pymilvus import DataType, MilvusClient, MilvusClient as _MilvusClient

from ..application.ports import VectorStore


class MilvusVectorStore:
    """把 chunk 行保存到注入/配置的 Milvus collection 中。

    全文检索由独立 LexicalStore（Elasticsearch）承担，Milvus 只保留 dense
    向量用于语义召回，不再写入或检索 sparse 向量。
    """

    def __init__(self, *, host: str, port: int, database: str,
                 collection: str, embedding_dim: int, user: str = "",
                 password: str = "", token: str | None = None):
        self._collection = collection
        self._dim = int(embedding_dim)
        uri = f"http://{host}:{port}"
        kwargs: dict[str, Any] = {"uri": uri, "db_name": database}
        if token:
            kwargs["token"] = token
        if user or password:
            if not user or not password:
                raise ValueError("Milvus 用户名和密码必须同时配置")
            kwargs["user"] = user
            kwargs["password"] = password
        self._client = MilvusClient(**kwargs)
        self._ensure_collection()

    def _ensure_collection(self) -> None:
        if not self._client.has_collection(collection_name=self._collection):
            schema = _MilvusClient.create_schema(auto_id=False, enable_dynamic_field=True)
            schema.add_field("chunk_id", DataType.VARCHAR, max_length=256, is_primary=True)
            schema.add_field("document_id", DataType.VARCHAR, max_length=128)
            schema.add_field("text", DataType.VARCHAR, max_length=65535)
            schema.add_field("search_text", DataType.VARCHAR, max_length=65535)
            schema.add_field("dense", DataType.FLOAT_VECTOR, dim=self._dim)
            self._client.create_collection(collection_name=self._collection, schema=schema)
        else:
            schema = self._client.describe_collection(self._collection)
            fields = {field.get("name"): field for field in schema.get("fields", [])}
            for required in ("chunk_id", "document_id", "text", "dense"):
                if required not in fields:
                    raise ValueError(f"Milvus collection 缺少必要字段: {required}")
            dense = fields.get("dense")
            if not dense or dense.get("type") not in (DataType.FLOAT_VECTOR, 101):
                raise ValueError("Milvus collection 缺少 dense 向量字段")
            if dense.get("params", {}).get("dim") != self._dim:
                raise ValueError(f"Milvus collection 向量维度不匹配: {dense.get('params', {}).get('dim')} != {self._dim}")
        self._ensure_index()
        self._client.load_collection(self._collection)

    def _index_matches(self, index_name: str) -> bool:
        info = self._client.describe_index(self._collection, index_name)
        return (info.get("index_type") == "AUTOINDEX" and
                info.get("metric_type") == "COSINE")

    def _ensure_index(self) -> None:
        indexes = self._client.list_indexes(self._collection, field_name="dense")
        if indexes:
            if not any(self._index_matches(index_name) for index_name in indexes):
                raise ValueError("Milvus dense 索引参数不匹配")
            return
        index_params = self._client.prepare_index_params()
        index_params.add_index(field_name="dense", index_type="AUTOINDEX",
                               metric_type="COSINE")
        self._client.create_index(self._collection, index_params)

    def has_document(self, document_id: str) -> bool:
        rows = self._client.query(self._collection, filter=f'document_id == "{_escape(document_id)}"', output_fields=["chunk_id", "document_id"], limit=1)
        return any(row.get("document_id") == document_id for row in rows)

    def insert(self, rows: list[dict]) -> bool:
        if not rows:
            return True
        payload = []
        for index, row in enumerate(rows):
            item = dict(row)
            item.setdefault("chunk_id", f"{row['document_id']}:{index}")
            if not _valid_document_id(str(item["document_id"])):
                raise ValueError("非法 document_id")
            item["section_path"] = json.dumps(item.get("section_path", []), ensure_ascii=False)
            payload.append(item)
        # 使用 upsert 保证同一 document_id/index 重试时幂等，不产生重复主键。
        result = self._client.upsert(self._collection, payload)
        return result.get("upsert_count", len(payload)) == len(payload)

    def delete(self, document_id: str) -> int:
        if not _valid_document_id(document_id):
            raise ValueError("非法 document_id")
        result = self._client.delete(self._collection, filter=f'document_id == "{_escape(document_id)}"')
        return int(result.get("delete_count", 0))

    def search(self, vector: list[float], *, top_k: int = 10, filter: str = "") -> list[dict]:
        if not isinstance(top_k, int) or isinstance(top_k, bool) or not 1 <= top_k <= 100:
            raise ValueError("top_k 必须是 1 到 100 之间的整数")
        if not isinstance(vector, list) or len(vector) != self._dim:
            raise ValueError(f"查询向量维度必须为 {self._dim}")
        if filter and not _valid_filter(filter):
            raise ValueError("非法 Milvus 过滤条件")
        result = self._client.search(self._collection, data=[vector], anns_field="dense", limit=top_k,
                                     filter=filter, output_fields=["chunk_id", "document_id", "text", "page", "kind", "section_path"])
        return [dict(item["entity"], score=item["distance"]) for item in (result[0] if result else [])]

    def chunk_exists(self, chunk_ids: Iterable[str]) -> dict[str, bool]:
        """返回 {chunk_id: 是否在库中}。批量按 primary key 查询，供评测标注校验。"""
        ids = list(dict.fromkeys(chunk_ids))
        found: set[str] = set()
        for batch in _batches(ids, 1000):
            expr = "chunk_id in [" + ",".join(f'"{_escape(item)}"' for item in batch) + "]"
            rows = self._client.query(self._collection, filter=expr,
                                      output_fields=["chunk_id"], limit=len(batch))
            found.update(row["chunk_id"] for row in rows)
        return {item: (item in found) for item in ids}


def _valid_document_id(value: str) -> bool:
    import re
    return bool(re.fullmatch(r"[A-Fa-f0-9]{32,64}", value))


def _valid_filter(value: str) -> bool:
    import re
    return bool(re.fullmatch(
        r'document_id\s*==\s*"[A-Fa-f0-9]{32,64}"', value))


def _escape(value: str) -> str:
    if not value or any(char in value for char in "\r\n\x00"):
        raise ValueError("非法 document_id")
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _batches(items: list, size: int):
    """把列表按 size 切块；空输入不产生任何块。"""
    for start in range(0, len(items), size):
        yield items[start:start + size]
