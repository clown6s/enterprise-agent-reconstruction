"""Technical document chunker with heading and page metadata."""
import re

from ...domain.models import ChunkRecord, ParsedDocument

_PAGE = re.compile(r"^\[\[page:(\d+)\]\]$")
_CHAPTER = re.compile(r"^第\s*[0-9一二三四五六七八九十百千万]+\s*章\s+.+$")
_SECTION = re.compile(r"^\d+(?:\.\d+){1,3}\s+.+$")
_SPECIAL = re.compile(r"^(?:实验\s*[0-9一二三四五六七八九十]+(?:[-—][0-9一二三四五六七八九十]+)?|思考题|本章小结)(?:\s*[:：].*)?$")


def _split_code(text: str, limit: int):
    lines, parts, current, length = text.splitlines(), [], [], 0
    for line in lines:
        if current and length + len(line) + 1 > limit:
            parts.append("\n".join(current)); current, length = [], 0
        current.append(line); length += len(line) + 1
    if current: parts.append("\n".join(current))
    return parts or [text]


def _split_long(text: str, limit: int):
    rest = text.strip()
    while len(rest) > limit:
        cut = max((rest.rfind(mark, 0, limit) for mark in "。！？!?；;"), default=-1)
        cut = cut + 1 if cut >= limit // 2 else limit
        yield rest[:cut].strip(); rest = rest[cut:].strip()
    if rest: yield rest


class TechnicalChunker:
    """按章节标题和自然段切分技术类文档，并保留页码。"""
    def __init__(self, max_chars: int = 600): self.max_chars = max_chars

    def chunk(self, document: ParsedDocument, source=None) -> list[ChunkRecord]:
        # Layout-aware behavior is opt-in for the technical-book profile. Other
        # profiles keep their established text-based contract even for PDFs.
        if document.profile == "technical_book" and document.layout_blocks:
            return self._chunk_layout(document.layout_blocks)
        return self._chunk_text(document.text)

    def _chunk_layout(self, blocks):
        result, section = [], []
        for block in blocks:
            text = block.text.strip()
            if not text: continue
            if block.kind == "heading":
                section = [text]; continue
            kind = block.kind if block.kind in {"table", "figure", "caption", "footnote"} else "technical"
            for index, part in enumerate(_split_long(text, self.max_chars)):
                base = len(result)
                result.append(ChunkRecord(text=part, kind=kind, page=block.page or 1,
                    page_end=block.page, section_path=tuple(section), continuation=index > 0,
                    continuation_of=f"{kind}:{base}" if index == 0 else result[-1].continuation_of,
                    continuation_index=index,
                    metadata={**block.metadata, "content_type": block.kind or "text"}))
        return result

    def _chunk_text(self, text):
        result, section, paragraphs = [], [], []
        page = start_page = 1
        in_code, code_lines, code_page = False, [], 1

        def flush():
            nonlocal paragraphs
            value = " ".join(paragraphs).strip()
            for index, part in enumerate(_split_long(value, self.max_chars)) if value else []:
                if len(part) < 8 and index == 0: continue
                result.append(ChunkRecord(text=part, kind="technical", page=start_page,
                    page_end=page, section_path=tuple(section), continuation=index > 0,
                    continuation_of=f"technical:{len(result)}" if index == 0 else result[-1].continuation_of,
                    continuation_index=index))
            paragraphs = []

        for raw in text.splitlines():
            line = raw.strip()
            if line.startswith("```"):
                if not in_code: flush(); in_code, code_lines, code_page = True, [raw], page
                else:
                    code_lines.append(raw)
                    for i, part in enumerate(_split_code("\n".join(code_lines), self.max_chars)):
                        result.append(ChunkRecord(text=part, kind="code", page=code_page, page_end=page,
                            section_path=tuple(section), continuation=i > 0, continuation_index=i,
                            metadata={"content_type": "code"}))
                    in_code, code_lines = False, []
                continue
            if in_code: code_lines.append(raw); continue
            if not line: flush(); continue
            marker = _PAGE.fullmatch(line)
            if marker: flush(); page = int(marker.group(1)); continue
            if _CHAPTER.fullmatch(line): flush(); section = [line]; start_page = page; continue
            if _SECTION.fullmatch(line) or _SPECIAL.fullmatch(line):
                flush()
                if _SECTION.fullmatch(line):
                    level = line.split(" ", 1)[0].count(".") + 1
                    section = section[:max(0, level - 1)] + [line]
                start_page = page; continue
            if not paragraphs: start_page = page
            paragraphs.append(line)
        flush()
        return result
