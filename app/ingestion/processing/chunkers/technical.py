"""Technical document chunker with heading and page metadata."""
import re

from ...domain.models import ChunkRecord, ParsedDocument

_PAGE = re.compile(r"^\[\[page:(\d+)\]\]$")
_CHAPTER = re.compile(r"^第\s*[0-9一二三四五六七八九十百千万]+\s*章\s+.+$")
_SECTION = re.compile(r"^[1-9]\d*(?:\.\d+){1,3}\s+.+$")
_INTRO = {"引言", "全书结构", "如何阅读本书", "前置知识", "致谢"}
_AFTERWORD = re.compile(r"^(?:后记(?:\s*[:：].*)?|两朵乌云|模型与 Agent 的共同演进)$")


def _heading_level(text: str) -> int | None:
    if text in _INTRO:
        return 1 if text == "引言" else 2
    if _AFTERWORD.fullmatch(text):
        return 1 if text.startswith("后记") else 2
    if _CHAPTER.fullmatch(text):
        return 1
    if _SECTION.fullmatch(text) and len(text) <= 80:
        number, _, title = text.partition(" ")
        # 正文可能以“7.1 节已经……”开头；“节/本节/这一节”是叙述词，不是标题。
        if re.match(r"(?:节|本节|这一节|已经|讲透了)", title):
            return None
        return number.count(".") + 1
    return None


def _update_section(section: list[str], heading: str) -> list[str]:
    level = _heading_level(heading)
    if level is None:
        return section
    return section[:level - 1] + [heading]


def _split_code(text: str, limit: int | None):
    if limit is None:
        return [text]
    lines, parts, current, length = text.splitlines(), [], [], 0
    for line in lines:
        if current and length + len(line) + 1 > limit:
            parts.append("\n".join(current)); current, length = [], 0
        current.append(line); length += len(line) + 1
    if current: parts.append("\n".join(current))
    return parts or [text]


def _split_long(text: str, limit: int | None):
    rest = text.strip()
    if limit is None:
        if rest:
            yield rest
        return
    while len(rest) > limit:
        cut = max((rest.rfind(mark, 0, limit) for mark in "。！？!?；;"), default=-1)
        cut = cut + 1 if cut >= limit // 2 else limit
        yield rest[:cut].strip(); rest = rest[cut:].strip()
    if rest: yield rest


class TechnicalChunker:
    """按章节标题和自然段切分技术类文档，并保留页码。"""
    def __init__(self, max_chars: int | None = None):
        if max_chars is not None and max_chars <= 0:
            raise ValueError("max_chars 必须为正数")
        self.max_chars = max_chars

    def chunk(self, document: ParsedDocument, source=None) -> list[ChunkRecord]:
        # 仅技术书 profile 使用版面感知切分，其他 profile 继续使用原有文本路径。
        if document.profile == "technical_book" and document.layout_blocks:
            return self._chunk_layout(document.layout_blocks)
        return self._chunk_text(document.text)

    def _chunk_layout(self, blocks):
        result, section, paragraphs = [], [], []
        start_page = page = 1
        unit = 0
        has_content = False

        def flush():
            nonlocal paragraphs, unit, has_content
            text = "\n\n".join(paragraphs).strip()
            if not text:
                return
            unit += 1
            # 技术书小节是原子检索单元，不按长度、表格、图示或代码拆分。
            result.append(ChunkRecord(
                text=text, kind="technical", page=start_page, page_end=page,
                section_path=tuple(section), continuation=False,
                continuation_of=f"technical:{unit}", continuation_index=0,
                metadata={"content_type": "section"},
            ))
            paragraphs = []
            has_content = False

        for block in blocks:
            text = block.text.strip()
            if not text: continue
            if block.kind == "heading":
                # 版面解析可能把续页页眉再次输出为 heading；它与当前
                # section 相同，不是新节，直接丢弃，避免跨页重复切分。
                if section and text == section[-1]:
                    continue
                # 新标题必须与前一节正文分开；不能只依赖 has_content，
                # 因为版面块状态可能在跨页时被重置。
                if has_content:
                    flush()
                section = _update_section(section, text)
                if not paragraphs:
                    start_page = page = block.page or page
                paragraphs.append(text)
                continue
            if block.kind in {"table", "figure", "caption", "footnote"}:
                # 表格、图示等版面内容仍归入当前小节。
                if not paragraphs: start_page = block.page or page
                page = block.page or page
                paragraphs.append(text)
                has_content = True
                continue
            if not paragraphs: start_page = block.page or page
            page = block.page or page
            paragraphs.append(text)
            has_content = True
        flush()
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
            level = _heading_level(line)
            if level is not None:
                flush()
                section = _update_section(section, line)
                start_page = page; continue
            if not paragraphs: start_page = page
            paragraphs.append(line)
        if in_code:
            for i, part in enumerate(_split_code("\n".join(code_lines), self.max_chars)):
                result.append(ChunkRecord(text=part, kind="code", page=code_page, page_end=page,
                    section_path=tuple(section), continuation=i > 0, continuation_index=i,
                    metadata={"content_type": "code"}))
        flush()
        return result
