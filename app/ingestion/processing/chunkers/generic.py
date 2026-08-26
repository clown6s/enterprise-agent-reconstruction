"""Generic text chunker."""
from ...domain.models import DocumentSource, ParsedDocument, ChunkRecord


class GenericChunker:
    def __init__(self, max_chars: int = 600):
        self.max_chars = max_chars

    def chunk(self, document: ParsedDocument, source: DocumentSource) -> list[ChunkRecord]:
        text = document.text.strip()
        if not text:
            return []
        result = []
        for paragraph in (part.strip() for part in text.split("\n\n")):
            if not paragraph:
                continue
            while len(paragraph) > self.max_chars:
                cut = max((paragraph.rfind(mark, 0, self.max_chars)
                           for mark in "。！？!?；;"), default=-1)
                cut = cut + 1 if cut >= self.max_chars // 2 else self.max_chars
                result.append(ChunkRecord(paragraph[:cut].strip()))
                paragraph = paragraph[cut:].strip()
            if paragraph:
                result.append(ChunkRecord(paragraph))
        return result
