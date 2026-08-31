from app.ingestion.application.retrieve import RetrieveDocuments


class FakeEmbedder:
    def embed_batch(self, texts):
        return [[1.0, 2.0] for _ in texts]


class FakeVectors:
    def search(self, vector, *, top_k, filter):
        assert vector == [1.0, 2.0]
        return [{"chunk_id": "d1:1", "text": "命中", "score": 0.9, "document_id": "d1",
                 "page": 3, "kind": "prose", "section_path": "[\"第一章\"]"}]


class FakeLexical:
    def search(self, query, *, top_k, filter=""):
        return []


def test_retrieves_and_decodes_source_metadata():
    results = RetrieveDocuments(FakeEmbedder(), FakeVectors(), lexical=FakeLexical())\
        .execute_hybrid("问题", top_k=3)
    assert results[0].text == "命中"
    assert results[0].section_path == ("第一章",)
    assert results[0].page == 3


def test_empty_query_returns_no_results():
    assert RetrieveDocuments(FakeEmbedder(), FakeVectors(), lexical=FakeLexical())\
        .execute_hybrid("  ") == []


def test_rrf_score_ignores_raw_backend_scores():
    from app.ingestion.application.retrieval_strategies import _rrf
    rows = _rrf(
        [{"chunk_id": "dense", "score": 0.01}],
        [{"chunk_id": "lexical", "score": 9999}],
        lexical_weight=0.05,
    )
    assert rows[0]["chunk_id"] == "dense"
    assert rows[0]["score"] < 1


class FakeMultiVectors:
    def search(self, vector, *, top_k, filter):
        return [
            {"chunk_id": "c1", "text": "甲", "score": 0.9, "document_id": "d1"},
            {"chunk_id": "c2", "text": "乙", "score": 0.8, "document_id": "d1"},
            {"chunk_id": "c3", "text": "丙", "score": 0.7, "document_id": "d1"},
        ]


class FakeReranker:
    def __init__(self, ranking=None, exc=None):
        self.ranking = ranking or []
        self.exc = exc

    def rerank(self, query, texts, *, top_n):
        if self.exc:
            raise self.exc
        return [(i, s) for i, s in self.ranking if i < len(texts)][:top_n]


def test_no_reranker_keeps_retrieval_order():
    rows = RetrieveDocuments(FakeEmbedder(), FakeMultiVectors(), lexical=FakeLexical())\
        .execute_hybrid("问题", top_k=3)
    assert [r.chunk_id for r in rows] == ["c1", "c2", "c3"]


def test_rerank_orders_by_model_score_after_dedup():
    # 去重后 c1/c2/c3 三个候选；模型把 c3 排最前
    reranker = FakeReranker(ranking=[(2, 0.9), (0, 0.5), (1, 0.1)])
    retriever = RetrieveDocuments(FakeEmbedder(), FakeMultiVectors(),
                                  lexical=FakeLexical(), reranker=reranker)
    rows = retriever.execute_hybrid("问题", top_k=3)
    assert [r.chunk_id for r in rows] == ["c3", "c1", "c2"]
    assert rows[0].score == 0.9


def test_rerank_failure_falls_back_to_retrieval_order():
    reranker = FakeReranker(exc=RuntimeError("boom"))
    retriever = RetrieveDocuments(FakeEmbedder(), FakeMultiVectors(),
                                  lexical=FakeLexical(), reranker=reranker)
    rows = retriever.execute_hybrid("问题", top_k=3)
    # 调用失败不拖垮查询，退回召回序
    assert [r.chunk_id for r in rows] == ["c1", "c2", "c3"]


class _RawReranker:
    """逐字返回 ranking，不做任何清洗，用于验证应用层防御校验。"""

    def __init__(self, ranking):
        self.ranking = ranking

    def rerank(self, query, texts, *, top_n):
        return self.ranking


def _retrieve_with_ranking(ranking):
    retriever = RetrieveDocuments(FakeEmbedder(), FakeMultiVectors(),
                                  lexical=FakeLexical(),
                                  reranker=_RawReranker(ranking))
    return retriever.execute_hybrid("问题", top_k=3)


def test_rerank_out_of_range_index_falls_back():
    # 候选只有 c1/c2/c3，返回越界下标 99
    rows = _retrieve_with_ranking([(99, 0.9)])
    assert [r.chunk_id for r in rows] == ["c1", "c2", "c3"]


def test_rerank_duplicate_index_falls_back():
    rows = _retrieve_with_ranking([(0, 0.9), (0, 0.8), (1, 0.7)])
    assert [r.chunk_id for r in rows] == ["c1", "c2", "c3"]


def test_rerank_incomplete_results_falls_back():
    rows = _retrieve_with_ranking([(0, 0.9)])
    assert [r.chunk_id for r in rows] == ["c1", "c2", "c3"]
