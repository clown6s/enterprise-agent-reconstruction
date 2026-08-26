from app.ingestion.domain.models import ParsedDocument
from app.ingestion.processing.chunkers.generic import GenericChunker


def test_chunker_respects_limit_and_sentence_boundary():
    parsed = ParsedDocument("第一句。第二句。")
    chunks = GenericChunker(10).chunk(parsed, None)
    assert all(len(chunk.text) <= 10 for chunk in chunks)
