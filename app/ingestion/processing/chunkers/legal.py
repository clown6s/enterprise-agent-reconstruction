"""Legal/statutory document chunker plugin."""
import re

from ...domain.models import ChunkRecord, ParsedDocument

_ARTICLE = re.compile(r"^\s*(第\s*[0-9零一二三四五六七八九十百千万]+\s*条(?:之\s*[0-9零一二三四五六七八九十百千万]+)?)")
_LEVEL = re.compile(r"^\s*(第\s*[0-9零一二三四五六七八九十百千万]+\s*(?:编|篇|章|节))\s*")
_PAGE = re.compile(r"^\[\[page:(\d+)\]\]$")
_TOC_TITLE = re.compile(r"^目\s*录$|^contents$", re.I)
_SEPARATOR = re.compile(r"^[╌─－—_—=~-]{2,}$")
_TOC_LINE = re.compile(r"^(第\s*[0-9零一二三四五六七八九十百千万]+\s*(?:编|篇|章|节))\s+(?:第\s*[0-9零一二三四五六七八九十百千万]+\s*条)?.{0,40}\s*[0-9]{1,4}\s*$")


def _split_long(text: str, limit: int):
    rest = text.strip()
    while len(rest) > limit:
        cut = max((rest.rfind(mark, 0, limit) for mark in "。！？!?；;"), default=-1)
        cut = cut + 1 if cut >= limit // 2 else limit
        yield rest[:cut].strip()
        rest = rest[cut:].strip()
    if rest:
        yield rest


class LegalChunker:
    """Keep each article together and retain section/continuation metadata."""
    def __init__(self, max_chars: int = 600):
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

        for raw in document.text.splitlines():
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
                # 同级章节替换旧章节：编/篇为一级，章为二级，节为三级。
                rank = {"编": 1, "篇": 1, "章": 2, "节": 3}.get(level_label[-1], 2)
                section = section[:rank - 1] + [label]
                remainder = line[level.end():].strip()
                if remainder:
                    self._start_article(remainder, page, section, units, lambda value: None)
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
        # Reserved hook for inline article headings; ordinary documents use line starts.
        return None
