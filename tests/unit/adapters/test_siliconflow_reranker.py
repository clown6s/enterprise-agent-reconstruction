import pytest

from app.ingestion.adapters.siliconflow_reranker import (
    SiliconFlowReranker, SiliconFlowRerankError)


class _FakeResponse:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        return self._payload


class _FakePost:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def post(self, url, *, headers, json, timeout):
        self.calls.append((url, headers, json))
        return self.response


def _reranker(client):
    return SiliconFlowReranker("test-key", base_url="https://x.example/v1",
                               model="R", http_client=client)


def test_returns_sorted_index_score_pairs():
    fake = _FakePost(_FakeResponse(payload={"results": [
        {"index": 1, "relevance_score": 0.9},
        {"index": 0, "relevance_score": 0.3},
        {"index": 2, "relevance_score": 0.6},
    ]}))
    result = _reranker(fake).rerank("问题", ["甲", "乙", "丙"], top_n=3)
    assert result == [(1, 0.9), (2, 0.6), (0, 0.3)]
    assert fake.calls[0][0] == "https://x.example/v1/rerank"
    assert fake.calls[0][2]["documents"] == ["甲", "乙", "丙"]
    assert fake.calls[0][2]["top_n"] == 3
    assert fake.calls[0][2]["return_documents"] is False


def test_empty_input_returns_empty():
    fake = _FakePost(_FakeResponse())
    assert _reranker(fake).rerank("问题", [], top_n=1) == []
    assert fake.calls == []


def test_rejects_invalid_top_n():
    reranker = _reranker(_FakePost(_FakeResponse()))
    with pytest.raises(ValueError, match="top_n"):
        reranker.rerank("问题", ["甲"], top_n=0)
    with pytest.raises(ValueError, match="top_n"):
        reranker.rerank("问题", ["甲"], top_n=2)


def test_rejects_blank_query():
    with pytest.raises(ValueError, match="query"):
        _reranker(_FakePost(_FakeResponse())).rerank("  ", ["甲"], top_n=1)


def test_raises_on_out_of_range_index():
    fake = _FakePost(_FakeResponse(payload={"results": [
        {"index": 5, "relevance_score": 0.9},
    ]}))
    with pytest.raises(SiliconFlowRerankError, match="index"):
        _reranker(fake).rerank("问题", ["甲"], top_n=1)


def test_raises_on_duplicate_index():
    fake = _FakePost(_FakeResponse(payload={"results": [
        {"index": 0, "relevance_score": 0.9},
        {"index": 0, "relevance_score": 0.8},
    ]}))
    with pytest.raises(SiliconFlowRerankError, match="重复 index"):
        _reranker(fake).rerank("问题", ["甲", "乙"], top_n=2)


def test_raises_on_non_finite_score():
    fake = _FakePost(_FakeResponse(payload={"results": [
        {"index": 0, "relevance_score": float("nan")},
    ]}))
    with pytest.raises(SiliconFlowRerankError, match="分数无效"):
        _reranker(fake).rerank("问题", ["甲"], top_n=1)


def test_raises_on_count_mismatch():
    fake = _FakePost(_FakeResponse(payload={"results": [
        {"index": 0, "relevance_score": 0.9},
    ]}))
    with pytest.raises(SiliconFlowRerankError, match="数量"):
        _reranker(fake).rerank("问题", ["甲", "乙"], top_n=2)


def test_raises_on_error_status():
    fake = _FakePost(_FakeResponse(status_code=401, text="unauthorized"))
    with pytest.raises(SiliconFlowRerankError, match="401"):
        _reranker(fake).rerank("问题", ["甲"], top_n=1)


def test_raises_on_malformed_response():
    fake = _FakePost(_FakeResponse(payload={"unexpected": []}))
    with pytest.raises(SiliconFlowRerankError, match="结构无效"):
        _reranker(fake).rerank("问题", ["甲"], top_n=1)
