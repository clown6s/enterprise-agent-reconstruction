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
from app.ingestion.bootstrap.container import build_ingestion


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--mode", choices=("dense", "hybrid"), default="hybrid")
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--output")
    args = parser.parse_args()
    if args.top_k < 10:
        parser.error("--top-k 至少为 10，以同时计算 Recall@5 和 Recall@10")
    cases = load_cases(args.dataset)
    service = build_ingestion()
    retriever = RetrieveDocuments(service.embedder, service.vectors,
                                  sparse_embedder=service.sparse_embedder)
    if args.mode == "dense":
        class DenseOnly:
            def execute(self, query, *, top_k=10, filter=""):
                return retriever.execute(query, top_k=top_k, filter=filter)
        target = DenseOnly()
    else:
        class Hybrid:
            def execute(self, query, *, top_k=10, filter=""):
                return retriever.execute_hybrid(query, top_k=top_k, filter=filter)
        target = Hybrid()
    report = RetrievalEvaluationRunner(target).run(cases, ks=(5, 10))
    report["mode"] = args.mode
    report["dataset"] = str(args.dataset)
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(payload + "\n", encoding="utf-8")
    print(json.dumps(report["metrics"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
