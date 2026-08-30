"""Run a retrieval evaluation dataset against the configured read-only retriever."""
import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.ingestion.application.evaluation.dataset import load_cases
from app.ingestion.application.evaluation.runner import RetrievalEvaluationRunner
from app.ingestion.application.retrieve import RetrieveDocuments
from app.ingestion.bootstrap.container import build_ingestion
from app.ingestion.bootstrap.logging import setup_logging


def main() -> int:
    setup_logging()
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--mode", choices=("dense", "hybrid"),
                        default="hybrid")
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--output")
    args = parser.parse_args()
    if args.top_k < 10:
        parser.error("--top-k 至少为 10，以同时计算 Recall@5 和 Recall@10")
    cases = load_cases(args.dataset)
    service = build_ingestion()
    retriever = RetrieveDocuments(service.embedder, service.vectors,
                                  lexical=service.lexical,
                                  lexical_weight=float(os.getenv("ES_LEXICAL_WEIGHT", "0.25")))
    ks = (5, 10) if args.top_k == 10 else tuple(sorted({5, 10, args.top_k}))
    report = RetrievalEvaluationRunner(retriever).run(cases, ks=ks, mode=args.mode)
    report["dataset"] = str(args.dataset)
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(payload + "\n", encoding="utf-8")
    print(json.dumps(report["metrics"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
