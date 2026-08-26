"""Generic text chunker."""
import re

from ...domain.models import DocumentSource, ParsedDocument, ChunkRecord

_CATEGORY = re.compile(r"^\d+[．.、]\s*(\S+)$")
_ENTRY = re.compile(r"^([^：:]{1,30})[：:]\s*(.+)$")


def _split_long(text: str, limit: int):
    rest = text.strip()
    while len(rest) > limit:
        cut = max((rest.rfind(mark, 0, limit) for mark in "。！？!?；;"), default=-1)
        cut = cut + 1 if cut >= limit // 2 else limit
        yield rest[:cut].strip()
        rest = rest[cut:].strip()
    if rest:
        yield rest


class GenericChunker:
    def __init__(self, max_chars: int = 600):
        self.max_chars = max_chars

    def chunk(self, document: ParsedDocument, source: DocumentSource) -> list[ChunkRecord]:
        text = document.text.strip()
        if not text:
            return []
        lines = [line.strip() for line in text.splitlines()]
        entries = []
        category = ""
        current_name = ""
        current_body = []

        def flush():
            if current_body:
                entries.append((category, current_name, " ".join(current_body)))

        for line in lines:
            if not line:
                continue
            category_match = _CATEGORY.fullmatch(line)
            if category_match:
                flush(); current_name = ""; current_body = []
                category = category_match.group(1)
                continue
            entry_match = _ENTRY.fullmatch(line)
            if entry_match:
                flush()
                current_name = entry_match.group(1).strip()
                current_body = [entry_match.group(2).strip()]
            elif current_body:
                current_body.append(line)
            else:
                entries.append((category, "", line))
        flush()
        if not entries:
            entries = [("", "", text)]

        result = []
        for category, name, body in entries:
            prefix = f"类别：{category}\n" if category else ""
            prefix += f"条目：{name}\n" if name else ""
            for part in _split_long(prefix + body, self.max_chars):
                result.append(ChunkRecord(part))
        return result
