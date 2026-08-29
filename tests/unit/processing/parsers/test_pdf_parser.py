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


def test_technical_book_removes_next_heading_used_as_continuation_header():
    pages = [
        PageContent(1, "7.5 何时选择 SFT，何时选择 RL\n7.5 正文。"),
        PageContent(2, "7.6 单轮强化学习：记忆与泛化的对照\n7.5 后续正文。"),
        PageContent(3, "7.6 单轮强化学习：记忆与泛化的对照\n7.6 正文。"),
    ]
    parser = PdfParser(remove_positioned_headers=True)
    parser._extract_with_pdfplumber = lambda data: pages
    result = parser.parse(DocumentSource("book.pdf", b"x"))
    assert "7.5 后续正文。" in result.text
    assert result.text.count("7.6 单轮强化学习：记忆与泛化的对照") == 1
    assert any(block.text == "7.5 后续正文。" for block in result.layout_blocks)


def test_technical_book_keeps_first_page_heading_and_removes_later_header():
    pages = [
        PageContent(1, "7.6 标题\n首节正文。"),
        PageContent(2, "7.6 标题\n续页正文。"),
    ]
    parser = PdfParser(remove_positioned_headers=True)
    parser._extract_with_pdfplumber = lambda data: pages
    result = parser.parse(DocumentSource("book.pdf", b"x"))
    assert result.text.count("7.6 标题") == 1
    assert any(block.text == "续页正文。" for block in result.layout_blocks)


def test_keeps_article_start_at_page_top_during_positioned_header_cleanup():
    article = "第六条 各级人民政府指导家庭教育工作，建立健全家庭学校社会协同育人机制。"
    page = PageContent(
        2, article + "\n县级以上人民政府负责家庭教育工作。",
        lines=((article, 78.7), ("县级以上人民政府负责家庭教育工作。", 109.9)),
        height=800,
    )
    cleaned = PdfParser._remove_positioned_header(
        page.text.splitlines(), page.lines, page.height
    )
    assert cleaned[0] == article


def test_article_start_at_page_top_survives_parse():
    article = "第六条 各级人民政府指导家庭教育工作。"
    pages = [PageContent(1, "第五条 其他规定。"), PageContent(
        2, article + "\n县级以上人民政府做好家庭教育工作。",
        lines=((article, 78.7), ("县级以上人民政府做好家庭教育工作。", 109.9)),
        height=800,
    )]
    parser = PdfParser(remove_positioned_headers=True)
    parser._extract_with_pdfplumber = lambda data: pages
    result = parser.parse(DocumentSource("law.pdf", b"x"))
    assert article in result.text
