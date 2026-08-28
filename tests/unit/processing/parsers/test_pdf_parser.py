from app.ingestion.domain.models import DocumentSource
from app.ingestion.processing.parsers.pdf import PageContent, PdfParser


def test_filters_repeated_margin_lines_and_toc(monkeypatch):
    pages = [
        PageContent(1, "目录\n第一章 ........ 3\n第二章 ........ 8\n第三章 ........ 15"),
        PageContent(2, "章节标题\n正文内容。\n页脚"),
        PageContent(3, "章节标题\n更多正文。\n页脚"),
        PageContent(4, "章节标题\n最后正文。\n页脚"),
    ]
    monkeypatch.setattr(PdfParser, "_extract_with_pdfplumber", staticmethod(lambda data: pages))
    result = PdfParser().parse(DocumentSource("book.pdf", b"x"))
    assert "目录" not in result.text
    assert "章节标题" not in result.text
    assert "正文内容。" in result.text
    assert result.diagnostics["toc_pages"] == [1]
    assert result.diagnostics["removed_headers"] == 3
    assert result.diagnostics["removed_footers"] == 3
    assert [block.page for block in result.layout_blocks] == [2, 3, 4]


def test_keeps_one_off_heading():
    pages = [PageContent(1, "独有标题\n正文")]
    parser = PdfParser()
    parser._extract_with_pdfplumber = lambda data: pages
    result = parser.parse(DocumentSource("book.pdf", b"x"))
    assert "独有标题" in result.text


def test_removes_running_heading_repeated_in_page_body():
    pages = [PageContent(1, "4.3 工具生态：MCP 与工具选择的挑战\n"
                         "第三代优化的共同背景是工具数量的快速增长。\n"
                         "4.3 工具生态：MCP 与工具选择的挑战\n"
                         "在实际构建 Agent 工具集时，挑战是工具格式不一。")]
    parser = PdfParser()
    parser._extract_with_pdfplumber = lambda data: pages
    result = parser.parse(DocumentSource("book.pdf", b"x"))
    assert result.text.count("4.3 工具生态：MCP 与工具选择的挑战") == 1
    assert result.text.startswith("[[page:1]]\n第三代优化")
