from dataclasses import dataclass
import pytest
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


class DualModeRetriever:
    def __init__(self):
        self.calls = []

    def execute(self, query, *, top_k=10, filter=""):
        self.calls.append(("dense", query))
        return [Result({"chunk_id": "ok"}, ("第一章",))]

    def execute_hybrid(self, query, *, top_k=10, filter=""):
        self.calls.append(("hybrid", query))
        return [Result({"chunk_id": "ok"}, ("第一章",))]


def test_runner_hybrid_mode_uses_execute_hybrid():
    retriever = DualModeRetriever()
    report = RetrievalEvaluationRunner(retriever).run(
        [RetrievalCase("x", "问题", frozenset({"ok"}))], ks=(5,), mode="hybrid")
    assert retriever.calls == [("hybrid", "问题")]
    assert report["mode"] == "hybrid"
    assert report["metrics"]["recall@5"] == 1


def test_runner_rejects_unknown_mode():
    with pytest.raises(ValueError, match="不支持的评测模式"):
        RetrievalEvaluationRunner(FakeRetriever()).run(
            [RetrievalCase("x", "问题", frozenset({"ok"}))], mode="bm25")


def test_runner_rerank_mode_requires_retriever_support():
    with pytest.raises(ValueError, match="rerank"):
        RetrievalEvaluationRunner(FakeRetriever()).run(
            [RetrievalCase("x", "问题", frozenset({"ok"}))], mode="rerank")


def test_runner_rerank_mode_uses_execute_reranked():
    class RerankedRetriever:
        def execute_reranked(self, query, *, top_k=10, filter=""):
            return [Result({"chunk_id": "ok"}, ())]
    report = RetrievalEvaluationRunner(RerankedRetriever()).run(
        [RetrievalCase("x", "问题", frozenset({"ok"}))], ks=(5,), mode="rerank")
    assert report["mode"] == "rerank"
    assert report["metrics"]["recall@5"] == 1


def test_runner_buckets_metrics_by_query_kind():
    cases = [
        RetrievalCase("exact", "第八条 规定了什么", frozenset({"ok"})),
        RetrievalCase("section", "第一章 讲了什么", frozenset({"miss"})),
        RetrievalCase("semantic", "什么是股权激励", frozenset({"miss"})),
    ]
    report = RetrievalEvaluationRunner(FakeRetriever()).run(cases, ks=(5,))
    assert set(report["by_kind"]) == {"exact", "section", "semantic"}
    assert report["by_kind"]["exact"]["cases"] == 1
    assert report["by_kind"]["exact"]["metrics"]["recall@5"] == 1
    assert report["by_kind"]["semantic"]["metrics"]["recall@5"] == 0
    assert all(item["query_kind"] for item in report["details"])


class FlakyRetriever:
    def execute(self, query, *, top_k=10, filter=""):
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
