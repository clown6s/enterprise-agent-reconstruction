import pytest

from app.observability.es_log_sink import ElasticsearchLogSink
from app.observability.metrics import chat_requests_total
from app.observability.tracing import setup_tracing, shutdown_tracing, span


class FakeEs:
    def __init__(self, fail=False):
        self.fail = fail
        self.docs = []
    def index(self, *, index, document):
        if self.fail:
            raise RuntimeError("es down")
        self.docs.append((index, document))
    def close(self):
        pass


def test_es_log_sink_redacts_and_drops_sensitive_fields():
    client = FakeEs()
    sink = ElasticsearchLogSink(host="es", client=client)
    assert sink.emit({
        "trace_id": "t1", "password": "secret", "authorization": "Bearer abc",
        "message": "phone 13800138000",
    })
    doc = client.docs[0][1]
    assert "password" not in doc and "authorization" not in doc
    assert "13800138000" not in doc["message"]


def test_es_log_failure_does_not_raise():
    sink = ElasticsearchLogSink(host="es", client=FakeEs(fail=True))
    assert sink.emit({"trace_id": "t1"}) is False


def test_tracing_setup_and_span():
    provider = setup_tracing()
    assert provider is not None
    with span("unit.test", stage="test") as current:
        assert current is not None
    shutdown_tracing()
