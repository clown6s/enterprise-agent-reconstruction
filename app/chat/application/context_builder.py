"""Build bounded, cited context for the language model."""
from ..domain.models import Citation, RetrievalItem
from ..security.context_boundary import untrusted_context


class ContextBuilder:
    def __init__(self, *, max_chunks: int = 5, max_chars: int = 12000):
        self.max_chunks = max(1, max_chunks)
        self.max_chars = max(1000, max_chars)

    def build(self, items: list[RetrievalItem]) -> tuple[str, tuple[Citation, ...]]:
        selected: list[RetrievalItem] = []
        used = 0
        for item in items[:self.max_chunks]:
            text = item.text or ""
            if not text:
                continue
            remaining = self.max_chars - used
            if remaining <= 0:
                break
            if len(text) > remaining:
                text = text[:remaining]
                item = RetrievalItem(text=text, score=item.score,
                    document_id=item.document_id, chunk_id=item.chunk_id,
                    page=item.page, section_path=item.section_path,
                    metadata=item.metadata)
            selected.append(item)
            used += len(text)
        citations = tuple(Citation(
            source_type="document", source_id=item.chunk_id or item.document_id,
            document_id=item.document_id, chunk_id=item.chunk_id, page=item.page,
            title=item.metadata.get("title"),
        ) for item in selected)
        return untrusted_context(selected), citations
