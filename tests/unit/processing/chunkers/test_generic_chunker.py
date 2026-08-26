from app.ingestion.domain.models import ParsedDocument
from app.ingestion.processing.chunkers.generic import GenericChunker


def test_chunker_respects_limit_and_sentence_boundary():
    parsed = ParsedDocument("第一句。第二句。")
    chunks = GenericChunker(10).chunk(parsed, None)
    assert all(len(chunk.text) <= 10 for chunk in chunks)


def test_skips_separators_and_page_marks():
    parsed = ParsedDocument("标题\n----\n草：生命力。\n[[page:3]]\n---\n黄叶：凋零。")
    chunks = GenericChunker().chunk(parsed, None)
    texts = [c.text for c in chunks]
    assert "标题" in texts
    assert all("----" not in t and "---" not in t and "[[page" not in t for t in texts)
    assert any("草" in t for t in texts)
    assert any("黄叶" in t for t in texts)


def test_chunker_splits_category_entries():
    parsed = ParsedDocument("古代诗歌中常用的意象\n1．植物类\n草：生命力强。\n黄叶：凋零、别离。")
    chunks = GenericChunker().chunk(parsed, None)
    assert len(chunks) == 3
    assert "类别：植物类" in chunks[1].text
    assert "条目：草" in chunks[1].text
    assert "条目：黄叶" in chunks[2].text
