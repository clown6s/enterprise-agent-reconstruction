"""端到端文档入库测试：解析 -> 分类 -> 切分 -> Embedding -> Milvus 入库。

用法:
    .venv/Scripts/python.exe scripts/ingest_document_flow.py

说明:
    - 修改下方 DOCUMENT_PATH 指定要入库的文档。
    - 需要 .env 中已配置 SILICONFLOW_API_KEY 与 MILVUS_HOST 等。
    - 会把文档真正写入 Milvus，消耗一次向量化费用；请使用小文档测试。
    - 不删除/重建已有 collection，不自动清空数据。
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.ingestion.bootstrap.container import build_ingestion
from app.ingestion.domain.models import DocumentSource

# DOCUMENT_PATH = r"D:\datum\内科学.pdf"
# DOCUMENT_PATH = r"D:\datum\家庭教育促进法.pdf"
# DOCUMENT_PATH = r"D:\datum\中华人工共和国刑法.pdf"
# DOCUMENT_PATH = r"D:\datum\中华人民共和国治安管理处罚法_20250627.docx"
# DOCUMENT_PATH = r"D:\datum\导游面试问答.docx"
# DOCUMENT_PATH = r"D:\datum\AI-Agents-in-Depth-zh-CN.pdf"
DOCUMENT_PATH = r"D:\datum\古代诗歌常用意象.txt"



def main(argv: list[str]) -> int:
    path = Path(DOCUMENT_PATH.strip())
    if not path.is_file():
        print(f"文件不存在: {path}")
        return 1

    source = DocumentSource(path.name, path.read_bytes())
    print(f"文件: {path.name}")
    print(f"大小: {source.size} 字节")

    # 真实读取 .env 中的配置，SiliconFlow + Milvus 都启用。
    service = build_ingestion()
    print(f"Embedder: {type(service.embedder).__name__}")
    print(f"VectorStore: {type(service.vectors).__name__}")

    try:
        result = service.execute(source)
    except Exception as exc:  # 让 adapter 和外部的真实异常都暴露出来
        print(f"入库异常: {type(exc).__name__}: {exc}")
        return 1

    print(f"状态: {result.status.value}")
    print(f"chunk 数量: {result.chunks}")
    print(f"document_id: {result.document_id}")
    print(f"诊断: {result.diagnostics}")
    if result.message:
        print(f"消息: {result.message}")
    if result.warnings:
        print(f"警告: {list(result.warnings)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))