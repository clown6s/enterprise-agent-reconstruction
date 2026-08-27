"""查询 Milvus 中已入库文档的测试脚本。

修改下方 QUERY 后运行：
    .venv/Scripts/python.exe scripts/search_document.py
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.ingestion.application.retrieve import RetrieveDocuments
from app.ingestion.bootstrap.container import build_ingestion

QUERY = "古诗里柳象征什么？"
TOP_K = 5
FILTER = ""
SEARCH_MODE = "hybrid"  # "dense" 或 "hybrid"


def main() -> int:
    service = build_ingestion()
    retriever = RetrieveDocuments(service.embedder, service.vectors,
                                  sparse_embedder=service.sparse_embedder)
    if SEARCH_MODE == "hybrid":
        results = retriever.execute_hybrid(QUERY, top_k=TOP_K, filter=FILTER)
    else:
        results = retriever.execute(QUERY, top_k=TOP_K, filter=FILTER)
    print(f"问题: {QUERY}")
    print(f"召回数量: {len(results)}")
    print("=" * 80)
    for index, result in enumerate(results, 1):
        section = " > ".join(result.section_path)
        print(f"[{index}] score={result.score:.4f} page={result.page} "
              f"kind={result.kind} section={section}")
        print(f"document_id={result.document_id}")
        print(result.text)
        print("-" * 80)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
