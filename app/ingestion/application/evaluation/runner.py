from collections.abc import Iterable
from typing import Protocol

from ..retrieve import RetrievalResult
from .models import RetrievalCase
from .metrics import (hit_rate_at_k, noise_rate, recall_at_k, reciprocal_rank,
                      result_id, section_hit)


class Retriever(Protocol):
    def execute(self, query: str, *, top_k: int = 10,
                filter: str = "") -> Iterable[RetrievalResult]: ...


class RetrievalEvaluationRunner:
    def __init__(self, retriever: Retriever):
        self.retriever = retriever

    def run(self, cases: list[RetrievalCase], *, ks=(5, 10)) -> dict:
        if not isinstance(ks, (list, tuple, set)):
            raise ValueError("ks 必须是整数序列")
        if (not ks or any(not isinstance(k, int) or isinstance(k, bool) or k < 1 for k in ks)):
            raise ValueError("ks 必须包含正整数")
        ks = tuple(sorted(set(ks)))
        details = []
        for case in cases:
            try:
                results = list(self.retriever.execute(case.query, top_k=max(ks)) or ())
                ids = [result_id(result) for result in results]
                if any(value is None for value in ids):
                    raise ValueError("检索结果缺少 chunk_id")
            except Exception as exc:
                details.append({"case_id": case.case_id, "query": case.query,
                                "status": "error", "error": type(exc).__name__,
                                "message": str(exc)})
                continue
            item = {"case_id": case.case_id, "query": case.query, "status": "ok", "returned_ids": ids}
            for k in ks:
                item.update({f"hit_rate@{k}": hit_rate_at_k(ids, case.relevant_chunk_ids, k),
                    f"recall@{k}": recall_at_k(ids, case.relevant_chunk_ids, k),
                    f"noise_rate@{k}": noise_rate(ids, case.forbidden_chunk_ids, k),
                    f"section_hit@{k}": section_hit(results, case.expected_sections, k)})
            item["mrr"] = reciprocal_rank(ids, case.relevant_chunk_ids)
            details.append(item)
        n = len(details) or 1
        metric_names = [f"{name}@{k}" for k in ks for name in ("hit_rate", "recall", "noise_rate", "section_hit")] + ["mrr"]
        return {"cases": len(details), "metrics": {
            key: sum(item[key] for item in details) / n for key in metric_names}, "details": details}
