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
        rows = list(self._rows.values())
        if filter.startswith("chunk_id in ["):
            inner = filter[len('chunk_id in ['):-1]
            ids = [part.strip().strip('"') for part in inner.split(",")]
            rows = [r for r in rows if r["chunk_id"] in ids]
        return rows[:limit]

    def delete(self, collection_name, filter=""):
        ids = [cid for cid in self._rows if f'"{cid}"' in filter or "document_id" in filter]
        count = len(ids)
        for cid in ids:
            self._rows.pop(cid, None)
        return {"delete_count": count}

    def search(self, collection_name, data, anns_field, limit, filter="", output_fields=None):
        self.last_search_filter = filter
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


def test_chunk_exists_returns_presence_map(monkeypatch):
    monkeypatch.setattr("app.ingestion.adapters.milvus_vector_store.MilvusClient",
                        lambda **kw: _FakeMilvusClient())
    store = MilvusVectorStore(host="h", port=19530, database="d", collection="c", embedding_dim=4096)
    store.insert([{"document_id": "0123456789abcdef0123456789abcdef", "text": "hello",
                   "chunk_id": "0123456789abcdef0123456789abcdef:1", "dense": [0.1] * 4096}])
    result = store.chunk_exists(["0123456789abcdef0123456789abcdef:1", "missing:9"])
    assert result == {"0123456789abcdef0123456789abcdef:1": True, "missing:9": False}


def test_chunk_exists_dedups_and_handles_empty(monkeypatch):
    monkeypatch.setattr("app.ingestion.adapters.milvus_vector_store.MilvusClient",
                        lambda **kw: _FakeMilvusClient())
    store = MilvusVectorStore(host="h", port=19530, database="d", collection="c", embedding_dim=4096)
    assert store.chunk_exists([]) == {}
    assert store.chunk_exists(["a:1", "a:1"]) == {"a:1": False}


def test_search_accepts_bare_document_id_filter(monkeypatch):
    monkeypatch.setattr("app.ingestion.adapters.milvus_vector_store.MilvusClient",
                        lambda **kw: _FakeMilvusClient())
    store = MilvusVectorStore(host="h", port=19530, database="d", collection="c", embedding_dim=4096)
    doc = "0123456789abcdef0123456789abcdef"
    store.search([0.1] * 4096, top_k=5, filter=doc)
    assert store._client.last_search_filter == f'document_id == "{doc}"'


def test_search_empty_filter_passes_no_expression(monkeypatch):
    monkeypatch.setattr("app.ingestion.adapters.milvus_vector_store.MilvusClient",
                        lambda **kw: _FakeMilvusClient())
    store = MilvusVectorStore(host="h", port=19530, database="d", collection="c", embedding_dim=4096)
    store.search([0.1] * 4096, top_k=5, filter="")
    assert store._client.last_search_filter == ""


def test_search_rejects_invalid_filter(monkeypatch):
    monkeypatch.setattr("app.ingestion.adapters.milvus_vector_store.MilvusClient",
                        lambda **kw: _FakeMilvusClient())
    store = MilvusVectorStore(host="h", port=19530, database="d", collection="c", embedding_dim=4096)
    with pytest.raises(ValueError, match="非法 document_id"):
        store.search([0.1] * 4096, top_k=5, filter='document_id == "abc"')

