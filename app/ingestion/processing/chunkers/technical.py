"""Technical document chunker with heading and page metadata."""
import re

from ...domain.models import ChunkRecord, ParsedDocument

_PAGE = re.compile(r"^\[\[page:(\d+)\]\]$")
_CHAPTER = re.compile(r"^第\s*[0-9一二三四五六七八九十百千万]+\s*章\s+.+$")
_SECTION = re.compile(r"^\d+(?:\.\d+){1,3}\s+.+$")
_SPECIAL = re.compile(r"^(?:实验\s*[0-9一二三四五六七八九十]+(?:[-—][0-9一二三四五六七八九十]+)?|思考题|本章小结)(?:\s*[:：].*)?$")


def _split_code(text: str, limit: int):
    """代码块超长时优先按空行/行边界切，尽量避免在语句中间截断。"""
    lines = text.splitlines()
    parts = []
    current = []
    current_len = 0
    for line in lines:
        if current and current_len + len(line) + 1 > limit:
            parts.append("\n".join(current))
            current, current_len = [], 0
        current.append(line)
        current_len += len(line) + 1
    if current:
        parts.append("\n".join(current))
    return parts or [text]


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
        in_code = False
        code_lines: list[str] = []
        code_start_page = 1

        def flush():
            nonlocal paragraphs, start_page
            text = " ".join(paragraphs).strip()
            if text:
                for index, part in enumerate(_split_long(text, self.max_chars)):
                    if len(part) < 8 and index == 0:
                        continue
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
            if line.startswith("```"):
                if not in_code:
                    flush()
                    in_code = True
                    code_lines = [raw]
                    code_start_page = page
                else:
                    code_lines.append(raw)
                    code_text = "\n".join(code_lines)
                    if len(code_text) <= self.max_chars:
                        code_parts = [code_text]
                    else:
                        code_parts = list(_split_code(code_text, self.max_chars))
                    for code_index, code_part in enumerate(code_parts):
                        result.append(ChunkRecord(
                            text=code_part, kind="code", page=code_start_page,
                            page_end=page, section_path=tuple(section),
                            continuation=code_index > 0,
                            continuation_of=f"code:{len(result)}" if code_index == 0 else f"code:{len(result) - code_index}",
                            continuation_index=code_index,
                            metadata={"content_type": "code"},
                        ))
                    code_lines = []
                    in_code = False
                continue
            if in_code:
                code_lines.append(raw)
                continue
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
                if _SECTION.fullmatch(line):
                    level = line.split(" ", 1)[0].count(".") + 1
                    section = section[:max(0, level - 1)] + [line]
                start_page = page
                continue
            if not paragraphs:
                start_page = page
            paragraphs.append(line)
        flush()
        return result
