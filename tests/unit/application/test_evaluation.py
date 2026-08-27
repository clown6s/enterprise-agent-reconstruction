from dataclasses import dataclass
from app.ingestion.application.evaluation.metrics import hit_rate_at_k, recall_at_k, reciprocal_rank
from app.ingestion.application.evaluation.runner import RetrievalEvaluationRunner
from app.ingestion.application.evaluation.models import RetrievalCase


def test_metrics():
    ids = ["a", "b", "c"]
    assert hit_rate_at_k(ids, {"b"}, 2) == 1
    assert recall_at_k(ids, {"a", "c"}, 2) == .5
    assert reciprocal_rank(ids, {"b"}) == .5


@dataclass
class Result:
    metadata: dict
    section_path: tuple = ()


class FakeRetriever:
    def execute(self, query, *, top_k=10, filter=""):
        return [Result({"chunk_id": "ok"}, ("第一章",))]


def test_runner():
    report = RetrievalEvaluationRunner(FakeRetriever()).run(
        [RetrievalCase("x", "问题", frozenset({"ok"}), ("第一章",))], ks=(5, 10))
    assert report["metrics"]["recall@5"] == 1
    assert report["metrics"]["recall@10"] == 1
