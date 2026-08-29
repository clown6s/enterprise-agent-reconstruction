import pytest

from app.ingestion.application.retrieve import RetrieveDocuments


class FakeEmbedder:
    def embed_batch(self, texts):
        return [[1.0, 2.0] for _ in texts]


class FakeVectors:
    def search(self, vector, *, top_k, filter):
        assert vector == [1.0, 2.0]
        return [{"text": "命中", "score": 0.9, "document_id": "d1",
                 "page": 3, "kind": "prose", "section_path": "[\"第一章\"]"}]


def test_retrieves_and_decodes_source_metadata():
    results = RetrieveDocuments(FakeEmbedder(), FakeVectors()).execute("问题", top_k=3)
    assert results[0].text == "命中"
    assert results[0].section_path == ("第一章",)
    assert results[0].page == 3


def test_empty_query_returns_no_results():
    assert RetrieveDocuments(FakeEmbedder(), FakeVectors()).execute("  ") == []


class MultiRowVectors:
    def search(self, vector, *, top_k, filter):
        return [
            {"chunk_id": "c1", "text": "甲", "score": 0.9, "document_id": "d1"},
            {"chunk_id": "c2", "text": "乙", "score": 0.8, "document_id": "d1"},
            {"chunk_id": "c1", "text": "甲", "score": 0.7, "document_id": "d1"},
        ]


class FakeReranker:
    def __init__(self):
        self.seen_texts = None

    def rerank(self, query, texts, *, top_n):
        self.seen_texts = list(texts)
        # 下标越大分越高，与原向量分数相反，便于区分排序来源。
        return sorted(((index, float(index)) for index in range(len(texts))),
                      key=lambda pair: pair[1], reverse=True)


def test_reranked_orders_by_rerank_score_after_dedup():
    reranker = FakeReranker()
    results = RetrieveDocuments(
        FakeEmbedder(), MultiRowVectors(), reranker=reranker
    ).execute_reranked("问题", top_k=2)
    assert reranker.seen_texts == ["甲", "乙"]
    assert [result.text for result in results] == ["乙", "甲"]
    assert results[0].score == 1.0
    assert results[0].chunk_id == "c2"


def test_reranked_requires_reranker():
    with pytest.raises(ValueError, match="重排序"):
        RetrieveDocuments(FakeEmbedder(), FakeVectors()).execute_reranked("问题")


def test_reranked_empty_query_returns_no_results():
    assert RetrieveDocuments(
        FakeEmbedder(), FakeVectors(), reranker=FakeReranker()
    ).execute_reranked("  ") == []
