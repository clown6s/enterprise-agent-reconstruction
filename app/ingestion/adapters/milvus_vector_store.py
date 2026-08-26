"""Milvus 适配器（实现摄入存储相关端口）。"""
import json
from typing import Any

from pymilvus import DataType, MilvusClient, MilvusClient as _MilvusClient

from ..application.ports import VectorStore


class MilvusVectorStore:
    """把 chunk 行保存到注入/配置的 Milvus collection 中。"""

    def __init__(self, *, host: str, port: int, database: str,
                 collection: str, embedding_dim: int, token: str | None = None):
        self._collection = collection
        self._dim = int(embedding_dim)
        uri = f"http://{host}:{port}"
        kwargs: dict[str, Any] = {"uri": uri, "db_name": database}
        if token:
            kwargs["token"] = token
        self._client = MilvusClient(**kwargs)
        self._ensure_collection()

    def _ensure_collection(self) -> None:
        if not self._client.has_collection(collection_name=self._collection):
            schema = _MilvusClient.create_schema(auto_id=False, enable_dynamic_field=True)
            schema.add_field("chunk_id", DataType.VARCHAR, max_length=256, is_primary=True)
            schema.add_field("document_id", DataType.VARCHAR, max_length=128)
            schema.add_field("text", DataType.VARCHAR, max_length=65535)
            schema.add_field("dense", DataType.FLOAT_VECTOR, dim=self._dim)
            self._client.create_collection(collection_name=self._collection, schema=schema)
        else:
            schema = self._client.describe_collection(self._collection)
            vector = next((f for f in schema.get("fields", []) if f.get("name") == "dense"), None)
            if vector and vector.get("params", {}).get("dim") != self._dim:
                raise ValueError(f"Milvus collection 向量维度不匹配: {vector.get('params', {}).get('dim')} != {self._dim}")
        self._ensure_index()
        self._client.load_collection(self._collection)

    def _ensure_index(self) -> None:
        index_params = self._client.prepare_index_params()
        index_params.add_index(field_name="dense", index_type="AUTOINDEX", metric_type="COSINE")
        try:
            self._client.create_index(self._collection, index_params)
        except Exception:
            # 索引已存在时重建会抛错，忽略，仅需保证最终可加载。
            pass

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
            item["section_path"] = json.dumps(item.get("section_path", []), ensure_ascii=False)
            payload.append(item)
        result = self._client.insert(self._collection, payload)
        return result.get("insert_count", 0) == len(payload)

    def delete(self, document_id: str) -> int:
        result = self._client.delete(self._collection, filter=f'document_id == "{_escape(document_id)}"')
        return int(result.get("delete_count", 0))

    def search(self, vector: list[float], *, top_k: int = 10, filter: str = "") -> list[dict]:
        result = self._client.search(self._collection, data=[vector], anns_field="dense", limit=top_k,
                                     filter=filter, output_fields=["chunk_id", "document_id", "text", "page", "kind", "section_path"])
        return [dict(item["entity"], score=item["distance"]) for item in (result[0] if result else [])]


def _escape(value: str) -> str:
    return value.replace('\\', '\\\\').replace('"', '\\"')
