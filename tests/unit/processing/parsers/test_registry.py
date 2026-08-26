from app.ingestion.domain.models import DocumentSource
from app.ingestion.processing.parsers.csv import CsvParser
from app.ingestion.processing.parsers.registry import ParserRegistry
from app.ingestion.processing.parsers.text import TextParser


def test_registry_selects_by_extension():
    registry = ParserRegistry([TextParser(), CsvParser()])
    assert registry.parse(DocumentSource("a.csv", b"a,b")).parser == "csv"
