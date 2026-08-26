"""单独测试 DOCX 的问答切分；只读取文件，不调用 OCR、Embedding 或向量库。"""
from pathlib import Path

from app.ingestion.domain.models import DocumentSource
from app.ingestion.processing.parsers.docx import DocxParser
from app.ingestion.processing.qa import QaChunker, qa_confidence


# 只改这一行，填入要测试的 DOCX 文件完整路径。
DOCX_PATH = r"D:\datum\导游面试问答.docx"


def main() -> int:
    path = Path(DOCX_PATH.strip())
    if not DOCX_PATH.strip():
        print("请先在 DOCX_PATH = r\"\" 中填入 DOCX 文件路径")
        return 2
    if path.suffix.lower() != ".docx":
        print(f"请输入 .docx 文件: {path}")
        return 2
    if not path.is_file():
        print(f"文件不存在: {path}")
        return 1

    parsed = DocxParser().parse(DocumentSource(path.name, path.read_bytes()))
    confidence = qa_confidence(parsed)
    chunks = QaChunker().chunk(parsed)

    print(f"文件: {path}")
    print(f"QA 判断: {confidence}")
    print(f"Chunk 数量: {len(chunks)}")
    print("=" * 80)
    for index, chunk in enumerate(chunks, 1):
        print(f"[{index}] kind={chunk.kind} question_number={chunk.metadata.get('question_number')} "
              f"qa_status={chunk.metadata.get('qa_status')} "
              f"continuation={chunk.continuation}")
        print(chunk.text)
        print("-" * 80)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
