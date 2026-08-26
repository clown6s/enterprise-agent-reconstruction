import pytest

from app.ingestion.adapters.siliconflow_embedding import SiliconFlowEmbedder, SiliconFlowError


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

    def __call__(self, url, *, headers, json, timeout):
        self.calls.append((url, headers, json))
        return self.response


def _embedder():
    return SiliconFlowEmbedder("test-key", base_url="https://x.example/v1",
                               model="M", embedding_dim=4096)


def _vector():
    return [0.5] * 4096


def test_batch_embeds_in_provider_order(monkeypatch):
    fake = _FakePost(_FakeResponse(payload={"data": [
        {"index": 0, "embedding": _vector()},
        {"index": 1, "embedding": _vector()},
    ]}))
    monkeypatch.setattr("httpx.post", fake)
    result = _embedder().embed_batch(["a", "b"])
    assert len(result) == 2
    assert all(len(v) == 4096 for v in result)
    assert fake.calls[0][2]["input"] == ["a", "b"]


def test_reorders_out_of_order_response(monkeypatch):
    fake = _FakePost(_FakeResponse(payload={"data": [
        {"index": 1, "embedding": _vector()},
        {"index": 0, "embedding": _vector()},
    ]}))
    monkeypatch.setattr("httpx.post", fake)
    result = _embedder().embed_batch(["first", "second"])
    assert result[0] == _vector()
    assert result[1] == _vector()


def test_raises_on_dimension_mismatch(monkeypatch):
    fake = _FakePost(_FakeResponse(payload={"data": [
        {"index": 0, "embedding": [0.1, 0.2]},
    ]}))
    monkeypatch.setattr("httpx.post", fake)
    with pytest.raises(SiliconFlowError, match="维度"):
        _embedder().embed_batch(["a"])


def test_raises_on_count_mismatch(monkeypatch):
    fake = _FakePost(_FakeResponse(payload={"data": [
        {"index": 0, "embedding": _vector()},
    ]}))
    monkeypatch.setattr("httpx.post", fake)
    with pytest.raises(SiliconFlowError, match="数量"):
        _embedder().embed_batch(["a", "b"])


def test_raises_on_error_status(monkeypatch):
    fake = _FakePost(_FakeResponse(status_code=401, text="unauthorized"))
    monkeypatch.setattr("httpx.post", fake)
    with pytest.raises(SiliconFlowError, match="401"):
        _embedder().embed_batch(["a"])


def test_empty_input_returns_empty(monkeypatch):
    fake = _FakePost(_FakeResponse())
    monkeypatch.setattr("httpx.post", fake)
    assert _embedder().embed_batch([]) == []
    assert fake.calls == []
