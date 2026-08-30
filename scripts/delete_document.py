"""按 document_id 删除已入库文档的 Milvus、Elasticsearch 和 MySQL 数据。

用法:
    .venv/Scripts/python.exe scripts/delete_document.py <document_id>

说明:
    - 删除 Milvus 向量、Elasticsearch 全文文档和 MySQL 元数据。
    - 删除后轮询等待 Milvus 和 Elasticsearch 最终一致性。
    - 复用 build_ingestion() 装配的同一组件，不重复拼接连接逻辑。
"""
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# 填入要删除的 document_id；也可以在运行时传入命令行参数。
DOCUMENT_ID = "f2ac959f4e0c375dc8b021b09a6527b4"
DELETE_POLL_TIMEOUT = 30
DELETE_POLL_INTERVAL = 2

from app.ingestion.bootstrap.container import build_ingestion
from app.ingestion.bootstrap.logging import setup_logging


def _wait_for_deletion(vectors, lexical, document_id: str, timeout: float) -> bool:
    """轮询等待 Milvus 和 Elasticsearch 删除可见。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        milvus_gone = not vectors.has_document(document_id)
        es_gone = lexical is None or lexical.count_document(document_id) == 0
        if milvus_gone and es_gone:
            return True
        time.sleep(DELETE_POLL_INTERVAL)
    return (not vectors.has_document(document_id) and
            (lexical is None or lexical.count_document(document_id) == 0))


def main(argv: list[str]) -> int:
    setup_logging()
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
    print(f"Milvus 删除数量: {count}")

    lexical = getattr(service, "lexical", None)
    if lexical is not None:
        lexical_count = lexical.delete(document_id)
        print(f"Elasticsearch 删除数量: {lexical_count}")
    else:
        print("Elasticsearch 未配置，跳过删除")

    metadata = service.metadata
    if hasattr(metadata, "delete_by_document_id"):
        metadata_count = metadata.delete_by_document_id(document_id)
        print(f"MySQL 元数据删除数量: {metadata_count}")
    else:
        print(f"当前 MetadataStore({type(metadata).__name__}) 不支持删除元数据")
    confirmed = _wait_for_deletion(vectors, lexical, document_id, DELETE_POLL_TIMEOUT)
    print(f"删除确认: {'已不可见' if confirmed else '超时仍未确认（最终一致性未达到）'}")
    return 0 if confirmed else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
