"""Run the main IngestDocument flow on one real DOCX, fully offline."""
from pathlib import Path

from app.ingestion.bootstrap.container import build_ingestion
from app.ingestion.domain.models import DocumentSource
from app.ingestion.processing.profiles import default_profiles
from app.ingestion.processing.parsers.docx import DocxParser


# 只改这一行，填入要测试的 DOCX 文件完整路径。
DOCX_PATH = r"D:\datum\中华人民共和国治安管理处罚法_20250627.docx"


def main() -> int:
    if not DOCX_PATH.strip():
        print("请先在 DOCX_PATH = r\"\" 中填入 DOCX 文件路径")
        return 2
    path = Path(DOCX_PATH.strip())
    if not path.is_file():
        print(f"文件不存在: {path}")
        return 1
    content = path.read_bytes()
    source = DocumentSource(path.name, content)
    parsed = DocxParser().parse(source)
    classification = default_profiles().classify(parsed)
    result = build_ingestion().execute(source)
    print(f"文件: {path}")
    print(f"状态: {result.status}")
    print(f"Profile: {classification.kind} (confidence={classification.confidence:.3f})")
    print(f"文档ID: {result.document_id}")
    print(f"Chunk 数: {result.chunks}")
    print(f"诊断: {result.diagnostics}")
    print(f"消息: {result.message}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
