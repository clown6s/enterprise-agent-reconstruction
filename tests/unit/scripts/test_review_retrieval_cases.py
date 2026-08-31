from types import SimpleNamespace

import scripts.review_retrieval_cases as review
from scripts.review_retrieval_cases import SaveRequest, QueryRequest


class FakeStrategy:
    def __init__(self, rows):
        self.rows = rows

    def retrieve(self, query, top_k, filter=""):
        return list(self.rows)


class FakeReranker:
    def rerank(self, query, texts, *, top_n):
        return [(1, 0.9), (0, 0.1)]


class FakeRetriever:
    def __init__(self):
        dense = [
            {"chunk_id": "a", "text": "A", "score": 0.8, "document_id": "d"},
            {"chunk_id": "b", "text": "B", "score": 0.7, "document_id": "d"},
        ]
        lexical = [
            {"chunk_id": "b", "text": "B", "score": 3.0, "document_id": "d"},
            {"chunk_id": "a", "text": "A", "score": 2.0, "document_id": "d"},
        ]
        self.dense_strategy = FakeStrategy(dense)
        self.lexical_strategy = FakeStrategy(lexical)
        self.reranker = FakeReranker()
        self.rerank_pool = 100

    @staticmethod
    def _dedup(rows):
        result = {}
        for row in rows:
            result.setdefault(row["chunk_id"], row)
        return list(result.values())

    def _rerank(self, query, rows):
        ranked = self.reranker.rerank(query, [r["text"] for r in rows], top_n=len(rows))
        return [{**rows[i], "score": score} for i, score in ranked]


def test_search_returns_all_hybrid_stages(monkeypatch):
    monkeypatch.setattr(review, "_ensure_retriever", lambda: FakeRetriever())
    response = review.search(review.QueryRequest(query="问题", top_k=2))

    assert set(response["stages"]) == {"milvus", "es", "rrf", "rerank"}
    assert response["rerank_enabled"] is True
    assert response["stages"]["milvus"][0]["chunk_id"] == "a"
    assert response["stages"]["es"][0]["chunk_id"] == "b"
    assert response["stages"]["rerank"][0]["chunk_id"] == "b"
    assert response["stage_rank"]["b"]["milvus"] == 2
    assert response["stage_rank"]["b"]["es"] == 1
    assert response["stage_rank"]["b"]["rerank"] == 1
    assert response["candidates"] == response["stages"]["rerank"]


def test_save_records_relevant_rankings(monkeypatch, tmp_path):
    retriever = FakeRetriever()
    retriever.vectors = SimpleNamespace(chunk_exists=lambda ids: {i: True for i in ids})
    monkeypatch.setattr(review, "_ensure_retriever", lambda: retriever)
    monkeypatch.setattr(review, "REVIEW_PATH", tmp_path / "review.json")
    monkeypatch.setattr(review, "CASES_PATH", tmp_path / "cases.json")

    stage_rank = {
        "b": {"milvus": 2, "es": 1, "rrf": 1, "rerank": 1,
              "milvus_score": 0.7, "es_score": 3.0,
              "rrf_score": 0.031, "rerank_score": 0.9},
    }
    req = SaveRequest(
        id="review-x", query="问题",
        candidates=[{"chunk_id": "b", "rank": 1}],
        stages={"rerank": [{"chunk_id": "b"}]},
        stage_rank=stage_rank,
        relevant_chunk_ids=["b"], forbidden_chunk_ids=[], expected_sections=[],
    )
    res = review.save(req)
    assert "已保存" in res.get("message", "")
    saved = review.json.loads(review.REVIEW_PATH.read_text(encoding="utf-8"))
    assert saved[0]["relevant_rankings"] == {"b": stage_rank["b"]}
