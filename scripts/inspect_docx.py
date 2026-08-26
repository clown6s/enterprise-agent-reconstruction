"""Inspect one real DOCX locally; never calls OCR or indexing services."""
from collections import Counter
from pathlib import Path
import sys

from app.ingestion.domain.models import DocumentSource
from app.ingestion.processing.parsers.docx import DocxParser
from app.ingestion.processing.qa import QaChunker, qa_confidence


# 只改这一行，填入要测试的 DOCX 文件完整路径。
DOCX_PATH = r"D:\datum\导游面试问答.docx"


def main() -> int:
    path = Path(DOCX_PATH.strip())
    if path.suffix.lower() != ".docx":
        print(f"请输入 .docx 文件: {path}")
        return 2
    if not path.is_file():
        print(f"文件不存在: {path}")
        return 1

    source = DocumentSource(path.name, path.read_bytes())
    parsed = DocxParser().parse(source)
    qa = qa_confidence(parsed)
    chunks = QaChunker().chunk(parsed)
    counts = Counter(block.kind for block in parsed.layout_blocks)

    print(f"文件: {path}")
    print(f"大小: {path.stat().st_size} bytes")
    print(f"解析器: {parsed.parser}")
    print(f"诊断: {parsed.diagnostics}")
    print(f"Block 类型: {dict(counts)}")
    print(f"页标记: {parsed.text.count('[[page:')}")
    print(f"QA 判断: {qa}")
    print(f"QA chunk 数: {len(chunks)}")
    print("标题:")
    for block in parsed.layout_blocks:
        if block.kind == "heading":
            print(f"  level={block.metadata.get('level')} page={block.page}: {block.text}")
    print("前 3000 字符:")
    print(parsed.text[:3000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
