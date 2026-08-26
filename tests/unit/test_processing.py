from app.ingestion.domain.models import DocumentSource, ParsedDocument
from app.ingestion.processing.text import CsvParser, GenericChunker, ParserRegistry, TextParser
from app.ingestion.processing.profiles import default_profiles


def test_text_parser_encoding_fallback():
    source = DocumentSource("a.txt", "中文".encode("gbk"))
    assert TextParser().parse(source).text == "中文"


def test_csv_parser_normalizes_rows():
    source = DocumentSource("a.csv", "姓名,部门\n张三,研发".encode())
    assert CsvParser().parse(source).text == "姓名 | 部门\n张三 | 研发"


def test_registry_selects_by_extension():
    registry = ParserRegistry([TextParser(), CsvParser()])
    assert registry.parse(DocumentSource("a.csv", b"a,b")).parser == "csv"


def test_chunker_respects_limit_and_sentence_boundary():
    parsed = ParsedDocument("第一句。第二句。")
    chunks = GenericChunker(10).chunk(parsed, None)
    assert all(len(chunk.text) <= 10 for chunk in chunks)


def test_profile_falls_back_for_generic_text():
    result = default_profiles().classify(ParsedDocument("普通文本"))
    assert result.kind == "generic"
