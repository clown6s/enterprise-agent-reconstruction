"""Run the main IngestDocument flow on one real DOCX, fully offline.

Reads only; uses noop embedder/vector/metadata/original stores so no
external service is touched. Fill DOCX_PATH then run:
  .venv\\Scripts\\python.exe scripts\\run_main_flow.py
"""
from pathlib import Path
from collections import Counter

from app.ingestion.bootstrap.container import build_ingestion
from app.ingestion.domain.models import DocumentSource


# 只改这一行，填入要测试的 DOCX 文件完整路径。
DOCX_PATH = r""


def main() -> int:
    if not DOCX_PATH.strip():
        print("请先在 DOCX_PATH = r\"\" 中填入 DOCX 文件路径")
        return 2
    path = Path(DOCX_PATH.strip())
    if not path.is_file():
        print(f"文件不存在: {path}")
        return 1

    service = build_ingestion()
    result = service.execute(DocumentSource(path.name, path.read_bytes()))

    print(f"文件: {path}")
    print(f"状态: {result.status}")
    print(f"profile: {getattr(service, 'classifier', None) and ''}")
    kinds = Counter()
    if result.document_id:
        # noop vectors don't store rows; just report lifecycle status
        pass
    print(f"文档ID: {result.document_id}")
    print(f"Chunk 数: {result.chunks}")
    print(f"诊断: {result.diagnostics}")
    print(f"消息: {result.message}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())