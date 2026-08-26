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
        blocks = []
        parts = []
        for page in pages:
            text = self._clean_page(page.text, page.page_number)
            if text:
                parts.append(f"[[page:{page.page_number}]]")
                parts.append(text)
                blocks.append(LayoutBlock(text=text, kind="paragraph", page=page.page_number))
        diagnostics = {"pages": len(pages), "pages_with_text": len(blocks), "parser": parser_name}
        return ParsedDocument("\n".join(parts), tuple(blocks), diagnostics, parser=parser_name)

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
