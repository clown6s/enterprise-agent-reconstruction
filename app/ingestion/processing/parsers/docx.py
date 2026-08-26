"""DOCX parser: paragraphs, headings, tables, page breaks and image hook."""
import hashlib
import io
import re
from typing import Any

from ...domain.models import DocumentSource, LayoutBlock, ParsedDocument
from ...application.ports import ImageTextExtractor

_MAX_IMAGES = 12
_MAX_IMAGE_BYTES = 3 * 1024 * 1024
_MIN_IMAGE_BYTES = 100


def _is_page_break(run) -> bool:
    xml = run._r.xml
    return bool(re.search(r'<w:br[^>]*w:type="page"|<w:lastRenderedPageBreak\b', xml))


def _heading_level(paragraph) -> int | None:
    style = (getattr(getattr(paragraph, "style", None), "name", "") or "").lower().strip()
    match = re.search(r"(?:heading|标题|title)\s*([1-9])", style)
    if match:
        return int(match.group(1))
    if style in {"heading", "标题", "title"}:
        return 1
    return None


def _image_blobs(document) -> list[bytes]:
    seen: set[str] = set()
    blobs: list[bytes] = []
    for part in document.part.related_parts.values():
        if "image" not in (getattr(part, "content_type", "") or ""):
            continue
        raw = getattr(part, "blob", None)
        if not raw or not (_MIN_IMAGE_BYTES < len(raw) <= _MAX_IMAGE_BYTES):
            continue
        digest = hashlib.sha256(raw).hexdigest()
        if digest not in seen:
            seen.add(digest)
            blobs.append(raw)
    return blobs


class DocxParser:
    extensions = frozenset(("docx",))

    def __init__(self, image_extractor: ImageTextExtractor | None = None):
        self.image_extractor = image_extractor

    def parse(self, source: DocumentSource) -> ParsedDocument:
        import docx
        from docx.table import Table
        from docx.text.paragraph import Paragraph

        document = docx.Document(io.BytesIO(source.content))
        blocks: list[LayoutBlock] = []
        page = 1
        for child in document.element.body.iterchildren():
            if child.tag.endswith("}p"):
                paragraph = Paragraph(child, document)
                for run in paragraph.runs:
                    if _is_page_break(run):
                        page += 1
                        blocks.append(LayoutBlock("", kind="page_break", page=page))
                text = (paragraph.text or "").strip()
                if text:
                    level = _heading_level(paragraph)
                    blocks.append(LayoutBlock(text, kind="heading" if level else "paragraph",
                                              page=page, metadata={"level": level} if level else {}))
            elif child.tag.endswith("}tbl"):
                for row in Table(child, document).rows:
                    cells = [cell.text.strip().replace("\n", " ") for cell in row.cells]
                    cells = [cell for cell in cells if cell]
                    if cells:
                        blocks.append(LayoutBlock(" | ".join(cells), kind="table", page=page,
                                                  metadata={"cells": cells, "columns": len(cells)}))

        warnings = []
        if self.image_extractor:
            for index, image in enumerate(_image_blobs(document)[:_MAX_IMAGES], 1):
                try:
                    text = self.image_extractor.extract(image, filename=source.filename, index=index).strip()
                except Exception as exc:
                    warnings.append(f"图片{index} OCR 失败: {type(exc).__name__}")
                    continue
                if text:
                    blocks.append(LayoutBlock(f"【图片{index}】{text}", kind="figure", page=page,
                                              metadata={"image_index": index, "ocr": True}))
        elif _image_blobs(document):
            warnings.append("未配置图片 OCR，已跳过内嵌图片")

        text_parts = []
        for block in blocks:
            if block.kind == "page_break":
                text_parts.append(f"[[page:{block.page}]]")
            elif block.kind == "heading":
                text_parts.append("#" * (block.metadata.get("level", 1) + 1) + " " + block.text)
            else:
                text_parts.append(block.text)
        diagnostics: dict[str, Any] = {"blocks": len(blocks), "pages": page}
        if warnings:
            diagnostics["warnings"] = warnings
        return ParsedDocument("\n".join(text_parts), tuple(blocks), diagnostics, parser="docx")
