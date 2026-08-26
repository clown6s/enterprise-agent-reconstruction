"""Legal/statutory document chunker plugin."""
import re

from ..domain.models import ChunkRecord, ParsedDocument

_ARTICLE = re.compile(r"^\s*(第\s*[0-9零一二三四五六七八九十百千万]+\s*条(?:之\s*[0-9零一二三四五六七八九十百千万]+)?)")
_LEVEL = re.compile(r"^\s*(第\s*[0-9零一二三四五六七八九十百千万]+\s*(?:编|篇|章|节))")
_PAGE = re.compile(r"^\[\[page:(\d+)\]\]$")


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
        page = 1

        def flush():
            nonlocal current
            if not current:
                return
            for index, part in enumerate(_split_long(current["text"], self.max_chars)):
                units.append(ChunkRecord(
                    text=part, kind="legal", page=current["page"], page_end=page,
                    section_path=tuple(section), continuation=index > 0,
                    continuation_of=current["article"], continuation_index=index,
                    metadata={"article": current["article"]},
                ))
            current = None

        for raw in document.text.splitlines():
            line = raw.strip()
            if not line:
                continue
            marker = _PAGE.fullmatch(line)
            if marker:
                page = int(marker.group(1)); continue
            level = _LEVEL.match(line)
            if level:
                flush()
                label = level.group(1).strip()
                rank = {"编": 1, "篇": 1, "章": 2, "节": 3}.get(label[-1], 2)
                section = section[:rank - 1] + [label]
                remainder = line[level.end():].strip()
                if remainder:
                    self._start_article(remainder, page, section, units, lambda value: None)
                continue
            match = _ARTICLE.match(line)
            if match:
                flush()
                current = {"text": line, "page": page,
                           "article": re.sub(r"\s+", "", match.group(1))}
            elif current:
                current["text"] += " " + line
            else:
                units.extend(ChunkRecord(line, kind="legal", page=page,
                                         section_path=tuple(section),
                                         metadata={"quality_flag": "unclassified_legal_text"}) for _ in [0])
        flush()
        return units

    @staticmethod
    def _start_article(*args, **kwargs):
        # Reserved hook for inline article headings; ordinary documents use line starts.
        return None
