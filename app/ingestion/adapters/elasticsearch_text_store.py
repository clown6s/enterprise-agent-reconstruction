"""Elasticsearch lexical-search adapter."""
from functools import wraps
from typing import Any

try:
    from elasticsearch import Elasticsearch, helpers
except ImportError:  # 允许未安装 ES 客户端时运行不启用 ES 的测试/命令。
    Elasticsearch = None
    helpers = None

from ..domain.exceptions import ElasticsearchError


def _wrap_es_errors(fn):
    """把 ES 客户端抛出的异常统一封装成 ElasticsearchError，保留原始异常链。

    仅包装真实的 IO/网络/ES 异常；业务校验抛出的 ValueError / KeyError /
    TypeError 属于调用方输入问题，原样透传，不误判为基础设施故障。
    """
    @wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except ElasticsearchError:
            raise
        except (ValueError, KeyError, TypeError):
            raise
        except Exception as exc:
            raise ElasticsearchError(f"Elasticsearch 调用失败: {type(exc).__name__}") from exc
    return wrapper


class ElasticsearchTextStore:
    """Store and BM25-search chunk text without leaking ES details."""

    def __init__(self, *, host: str, index: str, username: str = "",
                 password: str = "", cert_fingerprint: str = "",
                 timeout: float = 10.0, synonyms_set: str = "enterprise-retrieval-synonyms",
                 client=None):
        if not host or not index:
            raise ValueError("ES host 和 index 不能为空")
        self._index = index
        self._synonyms_set = synonyms_set
        if client is not None:
            self._client = client
        else:
            if Elasticsearch is None:
                raise RuntimeError("未安装 elasticsearch 客户端")
            kwargs: dict[str, Any] = {"request_timeout": timeout}
            if username or password:
                if not username or not password:
                    raise ValueError("ES 用户名和密码必须同时配置")
                kwargs["basic_auth"] = (username, password)
            if cert_fingerprint:
                kwargs["ssl_assert_fingerprint"] = cert_fingerprint
            self._client = Elasticsearch(host, **kwargs)
        self._client.info()
        self._ensure_index()

    def _ensure_index(self) -> None:
        indices = self._client.indices
        if not indices.exists(index=self._index):
            indices.create(index=self._index, settings={"analysis": {
                "filter": {"business_synonyms": {
                    "type": "synonym", "synonyms_set": self._synonyms_set,
                    "updateable": True,
                }},
                "analyzer": {
                    "text_index": {"type": "custom", "tokenizer": "ik_max_word"},
                    "text_search": {"type": "custom", "tokenizer": "ik_smart",
                                    "filter": ["business_synonyms"]},
                },
            }}, mappings={"properties": {
                "chunk_id": {"type": "keyword"},
                "document_id": {"type": "keyword"},
                "text": {"type": "text", "analyzer": "text_index", "search_analyzer": "text_search"},
                "search_text": {"type": "text", "analyzer": "text_index", "search_analyzer": "text_search"},
                "title": {"type": "text", "analyzer": "text_index", "search_analyzer": "text_search"},
                "article": {"type": "keyword"},
                "section_path": {"type": "keyword"},
                "page": {"type": "integer"},
                "page_end": {"type": "integer"},
                "kind": {"type": "keyword"},
                "category": {"type": "keyword"},
                "entry": {"type": "keyword"},
                "question_number": {"type": "keyword"},
                "medical_item": {"type": "keyword"},
            }})
            return
        mapping = indices.get_mapping(index=self._index)
        props = next(iter(mapping.values())).get("mappings", {}).get("properties", {})
        for name, expected in (("chunk_id", "keyword"), ("document_id", "keyword"),
                               ("text", "text"), ("search_text", "text")):
            if props.get(name, {}).get("type") != expected:
                raise ValueError(f"ES index 字段 {name} mapping 不匹配")
        for name in ("text", "search_text", "title"):
            field = props.get(name, {})
            if field.get("analyzer") != "text_index" or field.get("search_analyzer") != "text_search":
                raise ValueError(f"ES index 字段 {name} IK mapping 不匹配")

    @_wrap_es_errors
    def upsert(self, rows: list[dict]) -> bool:
        actions = [{"_op_type": "index", "_index": self._index,
                    "_id": row["chunk_id"], "_source": _source(row)} for row in rows]
        if not actions:
            return True
        ok, errors = helpers.bulk(self._client, actions, raise_on_error=False,
                                  raise_on_exception=False)
        if errors:
            raise RuntimeError(f"ES 批量写入失败: {len(errors)} 条")
        return ok == len(actions)

    @_wrap_es_errors
    def count_document(self, document_id: str) -> int:
        result = self._client.count(index=self._index,
                                     query={"term": {"document_id": document_id}})
        return int(result.get("count", 0))

    @_wrap_es_errors
    def delete(self, document_id: str) -> int:
        result = self._client.delete_by_query(
            index=self._index, query={"term": {"document_id": document_id}},
            conflicts="proceed", refresh=True)
        return int(result.get("deleted", 0))

    @_wrap_es_errors
    def delete_chunks(self, chunk_ids: list[str]) -> int:
        """按 chunk_id 精确删除，避免抹掉同文档其他批次的数据。"""
        if not chunk_ids:
            return 0
        result = self._client.delete_by_query(
            index=self._index, query={"terms": {"chunk_id": chunk_ids}},
            conflicts="proceed", refresh=True)
        return int(result.get("deleted", 0))

    def close(self) -> None:
        """释放 Elasticsearch 客户端持有的连接。"""
        client = getattr(self, "_client", None)
        close = getattr(client, "close", None)
        if callable(close):
            close()

    @_wrap_es_errors
    def search(self, query: str, *, top_k: int = 10, filter: str = "") -> list[dict]:
        body = {"size": top_k, "query": {"multi_match": {
            "query": query, "fields": ["text^2", "search_text", "title"]}}}
        if filter:
            body["query"] = {"bool": {"must": [body["query"]],
                                        "filter": {"term": {"document_id": filter}}}}
        response = self._client.search(index=self._index, **body)
        hits = response.get("hits", {}).get("hits", [])
        return [dict(hit.get("_source", {}), score=float(hit.get("_score", 0.0)),
                     chunk_id=hit.get("_id")) for hit in hits]


def _source(row: dict) -> dict:
    allowed = ("chunk_id", "document_id", "text", "search_text", "title",
               "article", "section_path", "page", "page_end", "kind",
               "chunk_role", "continuation", "continuation_of", "continuation_index",
               "category", "entry", "question_number", "medical_item")
    return {key: _json_safe(row.get(key)) for key in allowed if key in row}


def _json_safe(value):
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return str(value)
