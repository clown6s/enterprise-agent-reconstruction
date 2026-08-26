from app.ingestion.domain.models import DocumentSource
from app.ingestion.processing.parsers.csv import CsvParser


def test_csv_parser_normalizes_rows():
    source = DocumentSource("a.csv", "姓名,部门\n张三,研发".encode())
    assert CsvParser().parse(source).text == "姓名 | 部门\n张三 | 研发"
