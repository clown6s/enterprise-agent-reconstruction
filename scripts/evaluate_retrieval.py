"""Run a retrieval evaluation dataset against the configured read-only retriever."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.ingestion.application.evaluation.dataset import load_cases
from app.ingestion.application.evaluation.runner import RetrievalEvaluationRunner
from app.ingestion.application.retrieve import RetrieveDocuments
from app.ingestion.bootstrap.container import build_ingestion, build_reranker
from app.ingestion.bootstrap.logging import setup_logging


def main() -> int:
    setup_logging()
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--rerank", action="store_true",
                        help="在召回后接入模型 rerank（需要 SILICONFLOW_API_KEY）")
    parser.add_argument("--rerank-pool", type=int, default=100,
                        help="送给 rerank 的候选池大小（默认 100）")
    parser.add_argument("--output")
    args = parser.parse_args()
    if args.top_k < 10:
        parser.error("--top-k 至少为 10，以同时计算 Recall@5 和 Recall@10")
    cases = load_cases(args.dataset)
    service = build_ingestion()
    reranker = build_reranker() if args.rerank else None
    retriever = RetrieveDocuments(service.embedder, service.vectors,
                                  lexical=service.lexical, reranker=reranker,
                                  rerank_pool=args.rerank_pool)
    try:
        ks = (5, 10) if args.top_k == 10 else tuple(sorted({5, 10, args.top_k}))
        report = RetrievalEvaluationRunner(retriever).run(cases, ks=ks)
    finally:
        retriever.close()
    report["dataset"] = str(args.dataset)
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(payload + "\n", encoding="utf-8")
    print(json.dumps(report["metrics"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
