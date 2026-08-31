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
    def execute_hybrid(self, query, *, top_k=10, filter=""):
        return [Result({"chunk_id": "ok"}, ("第一章",))]


def test_runner():
    report = RetrievalEvaluationRunner(FakeRetriever()).run(
        [RetrievalCase("x", "问题", frozenset({"ok"}), ("第一章",))], ks=(5, 10))
    assert report["metrics"]["recall@5"] == 1
    assert report["metrics"]["recall@10"] == 1


class RecordingRetriever:
    def __init__(self):
        self.calls = []

    def execute_hybrid(self, query, *, top_k=10, filter=""):
        self.calls.append(query)
        return [Result({"chunk_id": "ok"}, ("第一章",))]


def test_runner_uses_execute_hybrid():
    retriever = RecordingRetriever()
    report = RetrievalEvaluationRunner(retriever).run(
        [RetrievalCase("x", "问题", frozenset({"ok"}))], ks=(5,))
    assert retriever.calls == ["问题"]
    assert report["mode"] == "hybrid"
    assert report["metrics"]["recall@5"] == 1


class FlakyRetriever:
    def execute_hybrid(self, query, *, top_k=10, filter=""):
        if "失败" in query:
            raise RuntimeError("boom")
        return [Result({"chunk_id": "ok"}, ())]


def test_runner_aggregates_ok_cases_when_others_fail():
    cases = [
        RetrievalCase("bad", "触发失败", frozenset({"ok"})),
        RetrievalCase("good", "正常问题", frozenset({"ok"})),
    ]
    report = RetrievalEvaluationRunner(FlakyRetriever()).run(cases, ks=(5,))
    assert report["cases"] == 2
    assert report["errors"] == 1
    # 指标只对成功用例取平均，失败用例不进入分母。
    assert report["metrics"]["recall@5"] == 1
    statuses = {item["case_id"]: item["status"] for item in report["details"]}
    assert statuses == {"bad": "error", "good": "ok"}
