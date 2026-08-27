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
        page_number_lines = {str(page.page_number) for page in pages}
        repeated_footers.update(page_number_lines)
        toc_pages = {page.page_number for page, text in zip(pages, cleaned)
                     if self._is_toc_page(text) or self._is_front_matter_toc(text, page.page_number)}

        blocks = []
        parts = []
        removed_headers = removed_footers = 0
        for page, text in zip(pages, cleaned):
            if page.page_number in toc_pages:
                continue
            lines = text.splitlines()
            lines = self._remove_inline_page_number(lines, page.page_number)
            lines, _ = self._remove_inline_toc(lines)
            lines, removed = self._remove_margin_lines(lines, repeated_headers, top=True)
            removed_headers += removed
            lines, removed = self._remove_margin_lines(lines, repeated_footers, top=False)
            removed_footers += removed
            text = "\n".join(lines).strip()
            if text:
                parts.extend((f"[[page:{page.page_number}]]", text))
                for block_text, kind, metadata in self._classify_blocks(lines):
                    blocks.append(LayoutBlock(
                        text=block_text, kind=kind, page=page.page_number,
                        metadata=metadata,
                    ))
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
    def _remove_inline_page_number(lines: list[str], page_number: int) -> list[str]:
        """删除与 PDF 物理页码相同的行尾页脚数字。"""
        result = []
        for line in lines:
            cleaned = re.sub(rf"\s+{page_number}\s*$", "", line)
            result.append(cleaned)
        return result

    @staticmethod
    def _remove_inline_toc(lines: list[str]) -> tuple[list[str], int]:
        """从页面内部移除与正文混排的目录块。

        当一页中同时出现“目录”标题、若干裸章标题（第X章…）以及真正的条文时，
        把“目录”到正文开始前的目录片段删掉，避免目录内容被向量化。
        """
        start = next((i for i, ln in enumerate(lines)
                      if ln.strip() in ("目录", "目 录")), None)
        if start is None:
            return lines, 0
        # 收集目录标题之后、正文开始前的裸章节标题行
        end = start + 1
        body_start = None
        for i in range(start + 1, len(lines)):
            ln = lines[i].strip()
            if re.fullmatch(r"第\s*[0-9一二三四五六七八九十百千万]+\s*章.*", ln):
                end = i + 1
                continue
            if re.match(r"^\s*第\s*[0-9一二三四五六七八九十百千万]+\s*条", ln) or len(ln) > 15:
                body_start = i
                break
        if body_start is None or end <= start + 1:
            return lines, 0
        removed = lines[start:end]
        # 保留正文开始前第一个章节标题；其余章节行属于目录条目。
        actual_heading = lines[start + 1]
        return lines[:start] + [actual_heading] + lines[body_start:], len(removed) - 1

    @staticmethod
    def _is_front_matter_toc(text: str, page_number: int) -> bool:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if page_number > 20 or len(lines) < 4:
            return False
        headings = sum(bool(re.match(r"^(?:第\s*[一二三四五六七八九十百千万0-9]+\s*章|\d+(?:\.\d+){1,3})", line)) for line in lines)
        return headings >= 3 and any("图 0-" in line or "全书结构" in line for line in lines)

    @staticmethod
    def _is_toc_page(text: str) -> bool:
        """判断一页是否为目录页。

        不依赖固定前几行，而是结合目录标题与“标题 + 页码”密度信号。
        """
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if not lines:
            return False

        def norm(line: str) -> str:
            # 规范化全角空白、全角标点与数字，便于统一匹配。
            for src, dst in (("　", " "), ("．", "."), ("·", "."),
                             ("，", ","), ("：", ":")):
                line = line.replace(src, dst)
            line = re.sub(r"[．·…]", ".", line)
            return re.sub(r"[０-９]", lambda m: str(int(m.group(0)) - 65248), line)

        # 目录标题（可在较靠前的位置出现）
        title_idx = next((i for i, ln in enumerate(lines[:15])
                          if norm(ln).strip().lower() in ("目录", "contents", "目 录")), None)

        # 统计“标题 + 尾页码”样式的条目（点线/省略号/空白分隔，结尾为 1~3 位数字）
        entry_re = re.compile(r"(?:\.{2,}|…{2,}|\s)\s*([0-9]{1,3})\s*$")
        entries = sum(bool(entry_re.search(norm(ln))) for ln in lines)

        # 密集页码信号：页面约一半以上行以数字结尾
        page_dense = (entries / max(1, len(lines))) >= 0.4 if lines else False

        if title_idx is not None:
            # 有目录标题：只要存在一定数量的目录条目即判定
            return entries >= 2 and entries / max(1, len(lines)) >= 0.15
        # 无目录标题：但页码密集且条目绝对数量足够，也判定为目录页
        return page_dense and entries >= 5

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
        lines = [PdfParser._normalize_line(line) for line in (text or "").replace("\\n", "\n").splitlines()]
        while lines and not lines[-1]:
            lines.pop()
        if lines and re.fullmatch(r"(?:page\s*)?\d+", lines[-1], re.I):
            if lines[-1].isdigit() and int(lines[-1]) != page_number:
                return "\n".join(lines)
            lines.pop()
        return "\n".join(line for line in lines if line)

    @staticmethod
    def _normalize_line(line: str) -> str:
        line = line.replace("　", " ")
        line = re.sub(r"[ \t]+", " ", line).strip()
        # PDF extraction often inserts spaces inside ASCII identifiers.
        line = re.sub(r"(?<=[A-Za-z])\s+(?=[A-Za-z])", " ", line)
        line = re.sub(r"(?<=[一-鿿])(?=[A-Za-z0-9])", " ", line)
        line = re.sub(r"(?<=[A-Za-z0-9])(?=[一-鿿])", " ", line)
        return line

    @staticmethod
    def _classify_blocks(lines: list[str]) -> list[tuple[str, str, dict]]:
        blocks = []
        current = []
        boundary = re.compile(
            r"^(?:第\s*[0-9一二三四五六七八九十百千万]+\s*章|"
            r"\d+(?:\.\d+){1,3})\s+.+$")
        for line in lines:
            stripped = line.strip()
            # pdfplumber may concatenate a heading with the following text.
            heading_match = re.match(r"^(第\s*[0-9一二三四五六七八九十百千万]+\s*章\s+.+?)(?=\s+(?:第\s*[0-9一二三四五六七八九十百千万]+\s*章|\d+(?:\.\d+){1,3}\s+)|$)", stripped)
            if heading_match and heading_match.group(1) != stripped:
                if current:
                    blocks.append(PdfParser._classify_block(current)); current = []
                blocks.append((heading_match.group(1), "heading", {"content_type": "heading"}))
                stripped = stripped[len(heading_match.group(1)):].strip()
                if not stripped: continue
            if not stripped:
                if current:
                    blocks.append(PdfParser._classify_block(current))
                    current = []
                continue
            # Extracted tables may follow prose without a blank line. Split at
            # stable column-header signatures so the table remains searchable.
            if stripped in {"直觉理解 实现组件 学术概念（可选） 含义", "直觉理解 实现组件 学术概念(可选) 含义"}:
                if current:
                    blocks.append(PdfParser._classify_block(current)); current = []
                current.append("表格 " + stripped)
                continue
            if current and current[0].startswith("表格 "):
                current.append(stripped)
                continue
            # Headings and labelled figures/tables are hard boundaries even
            # when pdfplumber omitted paragraph spacing.
            labelled = re.match(r"^(?:图|图表|Figure|Fig\.?|表|Table)\s*[0-9一二三四五六七八九十.-]+", stripped, re.I)
            if not labelled:
                labelled = re.search(r"(?:图|图表|Figure|Fig\.?|表|Table)\s*[0-9一二三四五六七八九十.-]+", stripped, re.I)
            if boundary.fullmatch(stripped) or labelled:
                if labelled and labelled.start() == 0 and not re.match(r"^(?:图|图表|Figure|Fig\.?|表|Table)\s*[0-9一二三四五六七八九十.-]+\s+\S+", stripped, re.I):
                    labelled = None
                if current:
                    blocks.append(PdfParser._classify_block(current))
                    current = []
                kind = "heading" if boundary.fullmatch(stripped) else None
                if labelled and labelled.start() > 0:
                    prefix, stripped = stripped[:labelled.start()].strip(), stripped[labelled.start():]
                    if prefix:
                        blocks.append((prefix, "paragraph", {"content_type": "text"}))
                classified = PdfParser._classify_block([stripped])
                blocks.append((stripped, kind or classified[1],
                              {"content_type": "heading"} if kind else classified[2]))
            else:
                current.append(stripped)
        if current:
            blocks.append(PdfParser._classify_block(current))
        return blocks

    @staticmethod
    def _classify_block(lines: list[str]) -> tuple[str, str, dict]:
        text = "\n".join(lines).strip()
        first = lines[0].strip()
        figure = re.match(r"^(图|Figure|Fig\.?|图表)\s*([0-9一二三四五六七八九十.-]+)", first, re.I)
        table = re.match(r"^(表|表格|Table)\s*([0-9一二三四五六七八九十.-]+)?", first, re.I)
        footnote = re.match(r"^(?:[0-9]{1,2}|[*†‡])\\s*(?:[A-Za-z]|[一-鿿])", first)
        diagram = "·" in text and len(text) <= 180 and len(lines) <= 3
        if figure or diagram:
            metadata = {"content_type": "figure"}
            if figure:
                metadata["figure_number"] = figure.group(2)
            return text, "figure", metadata
        if table:
            return text, "table", {"content_type": "table", "table_number": table.group(2)}
        if footnote and len(first) < 180:
            return text, "footnote", {"content_type": "footnote"}
        return text, "paragraph", {"content_type": "text"}
