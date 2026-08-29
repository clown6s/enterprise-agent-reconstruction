from app.ingestion.bootstrap.container import build_ingestion
from app.ingestion.domain.models import DocumentSource
from tests.unit.processing.parsers.test_docx_parser import make_doc


class _FreshMetadata:
    def find_by_sha(self, digest):
        return None
    def record(self, *args):
        return None


def _service():
    return build_ingestion(metadata=_FreshMetadata(), mode="test")


def test_container_wires_parser_classifier_and_chunker_registry():
    service = _service()
    result = service.execute(DocumentSource("qa.txt", "1、你是谁？\n答：我是助手。".encode()))
    assert result.status.value == "ingested"
    assert result.chunks >= 1


def test_container_accepts_real_docx_bytes():
    service = _service()
    result = service.execute(DocumentSource("sample.docx", make_doc()))
    assert result.status.value == "ingested"
    assert result.chunks >= 1
