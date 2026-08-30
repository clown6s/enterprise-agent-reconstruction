"""Medical document chunker with numbered-item and page metadata."""
import re

from ...domain.models import ChunkRecord, ParsedDocument

_PAGE = re.compile(r"^\[\[page:(\d+)\]\]$")
_NUMBERED_ITEM = re.compile(r"^[1-9]\d*[、.．]\s*\S+")
# 只在行首或空白后识别编号，避免把 10、识别成 1 + 0、，也避免拆开小数/日期。
_INLINE_ITEM = re.compile(r"(?<!\S)(?=[1-9]\d{0,2}[、.．]\s*\S+)")
_HEADING = re.compile(r"^(?:第\s*[0-9一二三四五六七八九十百千万]+\s*[章节篇]|[一二三四五六七八九十]+[、.．])\s*\S+")


def _split_numbered_line(line: str) -> list[str]:
    """拆分行内条目，但不拆分条目编号中的数字。"""
    matches = list(re.finditer(r"(?<!\S)([1-9]\d*)[、.．](?=\s*\S)", line))
    if len(matches) <= 1:
        return [line]
    return [line[matches[i].start():matches[i + 1].start() if i + 1 < len(matches) else len(line)]
            for i in range(len(matches))]


def _split_long(text: str, limit: int | None):
    rest = text.strip()
    if limit is None:
        if rest:
            yield rest
        return
    while len(rest) > limit:
        cut = max((rest.rfind(mark, 0, limit) for mark in "。！？!?；;"), default=-1)
        cut = cut + 1 if cut >= limit // 2 else limit
        yield rest[:cut].strip()
        rest = rest[cut:].strip()
    if rest:
        yield rest


class MedicalChunker:
    """按医学主题和编号条目切分，并保留页码与章节路径。"""

    def __init__(self, max_chars: int | None = None):
        if max_chars is not None and max_chars <= 0:
            raise ValueError("max_chars 必须为正数")
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

        lines = (part.strip() for raw in document.text.splitlines()
                 for part in _split_numbered_line(raw) if part.strip())
        for raw in lines:
            line = raw.strip()
            if not line:
                continue
            marker = _PAGE.fullmatch(line)
            if marker:
                page = int(marker.group(1))
                continue
            if _HEADING.fullmatch(line) and not _NUMBERED_ITEM.match(line):
                flush()
                section = [line] if line.startswith("第") else section + [line]
                start_page = page
                continue
            if _NUMBERED_ITEM.match(line):
                flush()
                current = [line]
                start_page = page
                continue
            if not current:
                start_page = page
            current.append(line)
        flush()
        return result
