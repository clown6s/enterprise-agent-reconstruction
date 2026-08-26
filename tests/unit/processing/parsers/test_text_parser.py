from app.ingestion.domain.models import DocumentSource
from app.ingestion.processing.parsers.text import TextParser


def test_text_parser_encoding_fallback():
    source = DocumentSource("a.txt", "中文".encode("gbk"))
    assert TextParser().parse(source).text == "中文"
