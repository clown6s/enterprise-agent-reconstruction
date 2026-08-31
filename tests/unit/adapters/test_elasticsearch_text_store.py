import pytest

from app.ingestion.adapters.elasticsearch_text_store import ElasticsearchTextStore


def _props():
    def field(field_type, analyzer="text_index", search_analyzer="text_search"):
        return {"type": field_type, "analyzer": analyzer, "search_analyzer": search_analyzer}
    return {
        "chunk_id": {"type": "keyword"},
        "document_id": {"type": "keyword"},
        "text": field("text"),
        "search_text": field("text"),
        "title": field("text"),
    }


class _FakeESClient:
    def __init__(self):
        self.indices = _FakeIndices()
        self._last = {}

    def info(self):
        return {}

    def search(self, index=None, **body):
        self._last = body
        return {"hits": {"hits": []}}


class _FakeIndices:
    def exists(self, index=None):
        return True

    def get_mapping(self, index=None):
        return {index: {"mappings": {"properties": _props()}}}


def _make_store():
    client = _FakeESClient()
    store = ElasticsearchTextStore(host="h", index="idx", client=client)
    return store, client


def test_search_with_bare_document_id_filter():
    store, client = _make_store()
    doc = "0123456789abcdef0123456789abcdef"
    store.search("问题", top_k=5, filter=doc)
    body = client._last
    assert body["query"]["bool"]["filter"] == {"term": {"document_id": doc}}


def test_search_empty_filter_keeps_plain_query():
    store, client = _make_store()
    store.search("问题", top_k=5, filter="")
    body = client._last
    assert "bool" not in body["query"]
    assert "multi_match" in body["query"]


def test_search_uses_equal_weight_fulltext_fields():
    store, client = _make_store()
    store.search("问题", top_k=5, filter="")
    fields = client._last["query"]["multi_match"]["fields"]
    # 取消手动权重：三字段等权普通全文检索，不含 ^ 提升
    assert fields == ["text", "search_text", "title"]
    assert all("^" not in field for field in fields)


def test_search_rejects_invalid_filter():
    store, _ = _make_store()
    with pytest.raises(ValueError, match="非法 document_id"):
        store.search("问题", top_k=5, filter='document_id == "abc"')
