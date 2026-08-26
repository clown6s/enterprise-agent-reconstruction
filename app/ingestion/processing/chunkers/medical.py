"""Medical document chunker with numbered-item and page metadata."""
import re

from ...domain.models import ChunkRecord, ParsedDocument

_PAGE = re.compile(r"^\[\[page:(\d+)\]\]$")
_NUMBERED_ITEM = re.compile(r"^\d+[、.．]\s*\S+")
_HEADING = re.compile(r"^(?:第\s*[0-9一二三四五六七八九十百千万]+\s*[章节篇]|[一二三四五六七八九十]+[、.．])\s*\S+")


def _split_long(text: str, limit: int):
    rest = text.strip()
    while len(rest) > limit:
        cut = max((rest.rfind(mark, 0, limit) for mark in "。！？!?；;"), default=-1)
        cut = cut + 1 if cut >= limit // 2 else limit
        yield rest[:cut].strip()
        rest = rest[cut:].strip()
    if rest:
        yield rest


class MedicalChunker:
    """按医学主题和编号条目切分，并保留页码与章节路径。"""

    def __init__(self, max_chars: int = 600):
        self.max_chars = max_chars

    def chunk(self, document: ParsedDocument, source=None) -> list[ChunkRecord]:
        result: list[ChunkRecord] = []
        section: list[str] = []
        current: list[str] = []
        page = start_page = 1
        item_id = 0

        def flush():
            nonlocal current, item_id
            text = " ".join(current).strip()
            if text:
                item_id += 1
                parts = list(_split_long(text, self.max_chars))
                for index, part in enumerate(parts):
                    result.append(ChunkRecord(
                        text=part, kind="medical", page=start_page, page_end=page,
                        section_path=tuple(section), continuation=index > 0,
                        continuation_of=f"medical:{item_id}", continuation_index=index,
                        metadata={"medical_item": item_id},
                    ))
            current = []

        for raw in document.text.splitlines():
            line = raw.strip()
            if not line:
                flush()
                continue
            marker = _PAGE.fullmatch(line)
            if marker:
                flush()
                page = int(marker.group(1))
                continue
            if _HEADING.fullmatch(line) and not _NUMBERED_ITEM.fullmatch(line):
                flush()
                section = [line] if line.startswith("第") else section + [line]
                start_page = page
                continue
            if _NUMBERED_ITEM.fullmatch(line):
                flush()
                current = [line]
                start_page = page
                continue
            if not current:
                start_page = page
            current.append(line)
        flush()
        return result
