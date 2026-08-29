import json

import pytest

from app.ingestion.adapters.milvus_vector_store import MilvusVectorStore, _escape


class _FakeMilvusClient:
    """Mimics the subset of pymilvus.MilvusClient used by the adapter."""

    def __init__(self, dim=4096, existing=False, existing_dim=None):
        self._dim = dim
        self._existing = existing
        self._existing_dim = existing_dim
        self._rows = {}

    def has_collection(self, collection_name):
        return self._existing

    def describe_collection(self, collection_name):
        return {"fields": [
            {"name": "chunk_id", "type": 21, "params": {}},
            {"name": "document_id", "type": 21, "params": {}},
            {"name": "text", "type": 21, "params": {}},
            {"name": "dense", "type": 101, "params": {"dim": self._existing_dim}},
        ]}

    def create_collection(self, collection_name, schema):
        pass

    def list_indexes(self, collection_name, field_name=""):
        return []

    def prepare_index_params(self):
        return self

    def add_index(self, field_name, index_type, metric_type):
        return self

    def create_index(self, collection_name, index_params):
        pass

    def load_collection(self, collection_name):
        pass

    def upsert(self, collection_name, data):
        for row in data:
            self._rows[row["chunk_id"]] = row
        return {"upsert_count": len(data)}

    def query(self, collection_name, filter="", output_fields=None, limit=10):
        return [r for r in self._rows.values()][:limit]

    def delete(self, collection_name, filter=""):
        ids = [cid for cid in self._rows if f'"{cid}"' in filter or "document_id" in filter]
        count = len(ids)
        for cid in ids:
            self._rows.pop(cid, None)
        return {"delete_count": count}

    def search(self, collection_name, data, anns_field, limit, filter="", output_fields=None):
        return [[]]

    def hybrid_search(self, collection_name, reqs, ranker, limit, output_fields=None):
        self._hybrid_calls = getattr(self, "_hybrid_calls", [])
        self._hybrid_calls.append((reqs, limit))
        return [[]]


def _make_store():
    client = _FakeMilvusClient()
    store = MilvusVectorStore.__new__(MilvusVectorStore)
    store._dim = 4096
    store._client = client
    return store, client


def test_insert_maps_rows_and_defaults_chunk_id(monkeypatch):
    monkeypatch.setattr("app.ingestion.adapters.milvus_vector_store.MilvusClient", lambda **kw: _FakeMilvusClient())
    store = MilvusVectorStore(host="h", port=19530, database="d", collection="c", embedding_dim=4096)
    ok = store.insert([{"document_id": "0123456789abcdef0123456789abcdef", "text": "hello", "dense": [0.1] * 4096,
                        "section_path": ["第 1 章"]}])
    assert ok is True
    stored = next(v for v in store._client._rows.values())
    assert json.loads(stored["section_path"]) == ["第 1 章"]


def test_has_document(monkeypatch):
    monkeypatch.setattr("app.ingestion.adapters.milvus_vector_store.MilvusClient", lambda **kw: _FakeMilvusClient())
    store = MilvusVectorStore(host="h", port=19530, database="d", collection="c", embedding_dim=4096)
    store.insert([{"document_id": "0123456789abcdef0123456789abcdef", "text": "x", "dense": [0.1] * 4096}])
    assert store.has_document("0123456789abcdef0123456789abcdef") is True
    assert store.has_document("doc2") is False


def test_raises_on_dimension_mismatch(monkeypatch):
    monkeypatch.setattr("app.ingestion.adapters.milvus_vector_store.MilvusClient",
                        lambda **kw: _FakeMilvusClient(existing=True, existing_dim=128))
    with pytest.raises(ValueError, match="维度"):
        MilvusVectorStore(host="h", port=19530, database="d", collection="c", embedding_dim=4096)


def test_escape_quotes_and_backslashes():
    assert _escape('a"b\\c') == 'a\\"b\\\\c'


def _make_bm25_store(monkeypatch):
    monkeypatch.setattr("app.ingestion.adapters.milvus_vector_store.MilvusClient",
                        lambda **kw: _FakeMilvusClient())
    return MilvusVectorStore(host="h", port=19530, database="d", collection="c",
                             embedding_dim=4096, hybrid=True, bm25=True)


def _sparse_request(store):
    reqs, _ = store._client._hybrid_calls[-1]
    return next(req for req in reqs if req.anns_field == "sparse")


def test_bm25_requires_hybrid():
    with pytest.raises(ValueError, match="bm25"):
        MilvusVectorStore(host="h", port=19530, database="d", collection="c",
                          embedding_dim=4096, hybrid=False, bm25=True)


def test_bm25_schema_has_analyzer_and_function(monkeypatch):
    captured = {}

    class Client(_FakeMilvusClient):
        def create_collection(self, collection_name, schema):
            captured["schema"] = schema

    monkeypatch.setattr("app.ingestion.adapters.milvus_vector_store.MilvusClient",
                        lambda **kw: Client())
    store = MilvusVectorStore(host="h", port=19530, database="d", collection="c",
                              embedding_dim=4096, hybrid=True, bm25=True)
    assert store.sparse_input == "text"
    raw = str(captured["schema"].to_dict())
    assert "chinese" in raw
    assert "text_bm25" in raw


def test_bm25_insert_strips_client_sparse(monkeypatch):
    store = _make_bm25_store(monkeypatch)
    store.insert([{"document_id": "0123456789abcdef0123456789abcdef", "text": "黄河",
                   "dense": [0.1] * 4096, "sparse": {1: 1.0}}])
    stored = next(v for v in store._client._rows.values())
    assert "sparse" not in stored


def test_bm25_hybrid_search_passes_raw_text(monkeypatch):
    store = _make_bm25_store(monkeypatch)
    store.hybrid_search([0.1] * 4096, "黄河泥沙", top_k=5)
    req = _sparse_request(store)
    assert req.data == ["黄河泥沙"]
    assert req.param["metric_type"] == "BM25"


def test_bm25_hybrid_search_rejects_dict_sparse(monkeypatch):
    store = _make_bm25_store(monkeypatch)
    with pytest.raises(ValueError, match="文本"):
        store.hybrid_search([0.1] * 4096, {1: 1.0}, top_k=5)


def test_legacy_hybrid_search_passes_dict_with_ip(monkeypatch):
    monkeypatch.setattr("app.ingestion.adapters.milvus_vector_store.MilvusClient",
                        lambda **kw: _FakeMilvusClient())
    store = MilvusVectorStore(host="h", port=19530, database="d", collection="c",
                              embedding_dim=4096, hybrid=True)
    assert store.sparse_input == "vector"
    store.hybrid_search([0.1] * 4096, {1: 1.0}, top_k=5)
    req = _sparse_request(store)
    assert req.data == [{1: 1.0}]
    assert req.param["metric_type"] == "IP"


def test_search_request_routes_sparse_text(monkeypatch):
    from app.ingestion.domain.models import VectorSearchRequest
    store = _make_bm25_store(monkeypatch)
    request = VectorSearchRequest(tuple([0.1] * 4096), top_k=5, sparse_text="黄河")
    assert store.search_request(request) == []
    req = _sparse_request(store)
    assert req.data == ["黄河"]


def test_search_request_sparse_text_requires_bm25(monkeypatch):
    from app.ingestion.domain.models import VectorSearchRequest
    monkeypatch.setattr("app.ingestion.adapters.milvus_vector_store.MilvusClient",
                        lambda **kw: _FakeMilvusClient())
    store = MilvusVectorStore(host="h", port=19530, database="d", collection="c",
                              embedding_dim=4096, hybrid=True)
    request = VectorSearchRequest(tuple([0.1] * 4096), top_k=5, sparse_text="黄河")
    with pytest.raises(ValueError, match="BM25"):
        store.search_request(request)