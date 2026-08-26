"""按 document_id 删除已入库文档的 Milvus 向量。

用法:
    .venv/Scripts/python.exe scripts/delete_document.py <document_id>

说明:
    - 只删除 Milvus 中的向量数据；MySQL 元数据记录仍保留（现有
      MetadataStore 没有删除接口），如需完整删除请另行扩展。
    - 复用 build_ingestion() 装配的同一 MilvusVectorStore，不重复拼接连接逻辑。
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# 填入要删除的 document_id；也可以在运行时传入命令行参数。
DOCUMENT_ID = ""

from app.ingestion.bootstrap.container import build_ingestion


def main(argv: list[str]) -> int:
    document_id = argv[1].strip() if len(argv) >= 2 else DOCUMENT_ID.strip()
    if not document_id:
        print("请在 DOCUMENT_ID 中填入 document_id，或运行时传入命令行参数")
        return 2

    service = build_ingestion()
    vectors = service.vectors
    if not hasattr(vectors, "delete") or not hasattr(vectors, "has_document"):
        print(f"当前 VectorStore({type(vectors).__name__}) 不支持删除")
        return 1

    print(f"删除前 has_document: {vectors.has_document(document_id)}")
    count = vectors.delete(document_id)
    print(f"删除数量: {count}")
    print(f"删除后 has_document: {vectors.has_document(document_id)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
