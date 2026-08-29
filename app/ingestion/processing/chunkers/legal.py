"""Legal/statutory document chunker plugin."""
import re

from ...domain.models import ChunkRecord, ParsedDocument

_ARTICLE = re.compile(r"^\s*(第\s*[0-9零一二三四五六七八九十百千万]+\s*条(?:之\s*[0-9零一二三四五六七八九十百千万]+)?)")
_LEVEL = re.compile(r"^\s*(第\s*[0-9零一二三四五六七八九十百千万]+\s*(?:编|篇|章|节))\s*")
_PAGE = re.compile(r"^\[\[page:(\d+)\]\]$")
_TOC_TITLE = re.compile(r"^目\s*录$|^contents$", re.I)
_SEPARATOR = re.compile(r"^[╌─－—_—=~-]{2,}$")
_TOC_LINE = re.compile(r"^(第\s*[0-9零一二三四五六七八九十百千万]+\s*(?:编|篇|章|节))\s+(?:第\s*[0-9零一二三四五六七八九十百千万]+\s*条)?.{0,40}\s*[0-9]{1,4}\s*$")
# 仅在章节标题前有行首或空白边界时拆分；避免把“总则第四章第八节”
# 等正文中的法律引用误判为文档层级标题。
_INLINE_LEVEL = re.compile(
    r"(?<!\S)(?=第\s*[0-9零一二三四五六七八九十百千万]+\s*(?:编|篇|章|节))"
)


def _split_inline_levels(line: str) -> list[str]:
    parts = [part.strip() for part in _INLINE_LEVEL.split(line) if part.strip()]
    return parts or [line]


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


class LegalChunker:
    """Keep each article together and retain section/continuation metadata."""
    def __init__(self, max_chars: int | None = None):
        self.max_chars = max_chars

    def chunk(self, document: ParsedDocument, source=None) -> list[ChunkRecord]:
        units = []
        section: list[str] = []
        current: dict | None = None
        preamble: list[str] = []
        page = 1

        def flush_preamble():
            nonlocal preamble
            text = " ".join(preamble).strip()
            if text:
                for part in _split_long(text, self.max_chars):
                    units.append(ChunkRecord(
                        text=part, kind="legal", page=1, page_end=page,
                        section_path=(),
                        metadata={"content_role": "preamble"},
                    ))
            preamble = []

        def flush():
            nonlocal current
            if not current:
                return
            for index, part in enumerate(_split_long(current["text"], self.max_chars)):
                units.append(ChunkRecord(
                    text=part, kind="legal", page=current["page"], page_end=current["page_end"],
                    section_path=tuple(section), continuation=index > 0,
                    continuation_of=current["article"], continuation_index=index,
                    metadata={"article": current["article"]},
                ))
            current = None

        lines = (part for raw in document.text.splitlines() for part in _split_inline_levels(raw))
        for raw in lines:
            line = raw.strip()
            if not line or _SEPARATOR.fullmatch(line) or _TOC_TITLE.fullmatch(line):
                continue
            if _TOC_LINE.fullmatch(line):
                continue
            marker = _PAGE.fullmatch(line)
            if marker:
                page = int(marker.group(1)); continue
            level = _LEVEL.match(line)
            if level:
                flush()
                level_label = level.group(1).strip()
                label = line
                # 同级章节替换旧章节；有编/篇时章为二级，否则章为一级。
                kind = level_label[-1]
                has_book = bool(section and re.search(
                    r"第\s*[0-9零一二三四五六七八九十百千万]+\s*[编篇]", section[0]))
                rank = 1 if kind in "编篇" else (2 if kind == "章" and has_book else 1 if kind == "章" else 3 if has_book else 2)
                section = section[:rank - 1] + [label]
                continue
            match = _ARTICLE.match(line)
            if match:
                flush_preamble()
                flush()
                current = {"text": line, "page": page, "page_end": page,
                           "article": re.sub(r"\s+", "", match.group(1))}
            elif current:
                current["text"] += " " + line
            else:
                preamble.append(line)
        flush_preamble()
        flush()
        return units

    @staticmethod
    def _start_article(*args, **kwargs):
        # 预留行内条款标题的扩展点；普通文档仍按行首识别。
        return None
