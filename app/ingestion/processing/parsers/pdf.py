"""PDF 文档解析器，正文和内嵌图片分开输出。"""
import io
import re
from dataclasses import dataclass

from ...domain.models import DocumentSource, LayoutBlock, ParsedDocument


@dataclass(frozen=True)
class PageContent:
    """保存单页文本和页码。"""
    page_number: int
    text: str


class PdfParser:
    """使用 pdfplumber 提取文字，并通过可注入接口处理内嵌图片。"""
    extensions = frozenset(("pdf",))

    def __init__(self):
        pass

    def parse(self, source: DocumentSource) -> ParsedDocument:
        pages = self._extract_with_pdfplumber(source.content)
        parser_name = "pdfplumber"
        if not pages:
            pages = self._extract_with_pypdf(source.content)
            parser_name = "pypdf"

        cleaned = [self._clean_page(page.text, page.page_number) for page in pages]
        repeated_headers = self._repeated_margin_lines(cleaned, top=True)
        repeated_footers = self._repeated_margin_lines(cleaned, top=False)
        toc_pages = {page.page_number for page, text in zip(pages, cleaned)
                     if self._is_toc_page(text)}

        blocks = []
        parts = []
        removed_headers = removed_footers = 0
        for page, text in zip(pages, cleaned):
            if page.page_number in toc_pages:
                continue
            lines = text.splitlines()
            lines, removed = self._remove_margin_lines(lines, repeated_headers, top=True)
            removed_headers += removed
            lines, removed = self._remove_margin_lines(lines, repeated_footers, top=False)
            removed_footers += removed
            text = "\n".join(lines).strip()
            if text:
                parts.extend((f"[[page:{page.page_number}]]", text))
                blocks.append(LayoutBlock(text=text, kind="paragraph", page=page.page_number))
        diagnostics = {
            "pages": len(pages), "pages_with_text": len(blocks), "parser": parser_name,
            "toc_pages": sorted(toc_pages), "removed_headers": removed_headers,
            "removed_footers": removed_footers,
        }
        return ParsedDocument("\n".join(parts), tuple(blocks), diagnostics, parser=parser_name)

    @staticmethod
    def _repeated_margin_lines(texts: list[str], *, top: bool) -> set[str]:
        """找出至少在三页同一边缘重复出现的行，避免误删正文中的偶发行。"""
        counts = {}
        for text in texts:
            lines = [line.strip() for line in text.splitlines() if line.strip()]
            margin = lines[:2] if top else lines[-2:]
            for line in set(margin):
                counts[line] = counts.get(line, 0) + 1
        return {line for line, count in counts.items() if count >= 3 and len(line) <= 120}

    @staticmethod
    def _remove_margin_lines(lines: list[str], candidates: set[str], *, top: bool):
        indexes = range(min(2, len(lines))) if top else range(max(0, len(lines) - 2), len(lines))
        removed = 0
        indexes = set(indexes)
        result = [line for index, line in enumerate(lines)
                  if not (index in indexes and line.strip() in candidates)]
        removed = len(lines) - len(result)
        return result, removed

    @staticmethod
    def _is_toc_page(text: str) -> bool:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if not lines or not any(line == "目录" or line.lower() == "contents" for line in lines[:3]):
            return False
        entries = sum(bool(re.search(r"(?:\.{2,}|…{2,}|\s)\d{1,3}$", line)) for line in lines[1:])
        return entries >= 3

    @staticmethod
    def _extract_with_pdfplumber(data: bytes) -> list[PageContent]:
        try:
            import pdfplumber
            with pdfplumber.open(io.BytesIO(data)) as pdf:
                return [PageContent(i, page.extract_text() or "") for i, page in enumerate(pdf.pages, 1)]
        except Exception:
            return []

    @staticmethod
    def _extract_with_pypdf(data: bytes) -> list[PageContent]:
        try:
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(data))
            return [PageContent(i, page.extract_text() or "") for i, page in enumerate(reader.pages, 1)]
        except Exception:
            return []

    @staticmethod
    def _clean_page(text: str, page_number: int) -> str:
        lines = [line.strip() for line in (text or "").replace("\\n", "\n").splitlines()]
        while lines and not lines[-1]:
            lines.pop()
        if lines and re.fullmatch(r"(?:page\s*)?\d+", lines[-1], re.I):
            if lines[-1].isdigit() and int(lines[-1]) != page_number:
                return "\n".join(lines)
            lines.pop()
        return "\n".join(line for line in lines if line)
