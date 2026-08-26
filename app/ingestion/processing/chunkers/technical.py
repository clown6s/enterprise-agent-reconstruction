"""Technical document chunker with heading and page metadata."""
import re

from ...domain.models import ChunkRecord, ParsedDocument

_PAGE = re.compile(r"^\[\[page:(\d+)\]\]$")
_CHAPTER = re.compile(r"^第\s*[0-9一二三四五六七八九十百千万]+\s*章\s+.+$")
_SECTION = re.compile(r"^\d+(?:\.\d+){1,3}\s+.+$")
_SPECIAL = re.compile(r"^(?:实验\s*\S+|思考题|本章小结|图\s*\S+).+$")


def _split_long(text: str, limit: int):
    rest = text.strip()
    while len(rest) > limit:
        cut = max((rest.rfind(mark, 0, limit) for mark in "。！？!?；;"), default=-1)
        cut = cut + 1 if cut >= limit // 2 else limit
        yield rest[:cut].strip()
        rest = rest[cut:].strip()
    if rest:
        yield rest


class TechnicalChunker:
    """按章节标题和自然段切分技术类文档，并保留页码。"""

    def __init__(self, max_chars: int = 600):
        self.max_chars = max_chars

    def chunk(self, document: ParsedDocument, source=None) -> list[ChunkRecord]:
        result: list[ChunkRecord] = []
        section: list[str] = []
        paragraphs: list[str] = []
        page = 1
        start_page = 1

        def flush():
            nonlocal paragraphs, start_page
            text = " ".join(paragraphs).strip()
            if text:
                for index, part in enumerate(_split_long(text, self.max_chars)):
                    result.append(ChunkRecord(
                        text=part, kind="technical", page=start_page,
                        page_end=page, section_path=tuple(section),
                        continuation=index > 0,
                        continuation_of=f"technical:{len(result)}" if index else None,
                        continuation_index=index,
                    ))
            paragraphs = []

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
            if _CHAPTER.fullmatch(line):
                flush()
                section = [line]
                start_page = page
                continue
            if _SECTION.fullmatch(line) or _SPECIAL.fullmatch(line):
                flush()
                level = line.split(" ", 1)[0].count(".") + 1 if _SECTION.fullmatch(line) else len(section) + 1
                section = section[:max(0, level - 1)] + [line]
                start_page = page
                continue
            if not paragraphs:
                start_page = page
            paragraphs.append(line)
        flush()
        return result
