import pytest

from app.ingestion.application.retrieval_strategies import (
    DenseRetrievalStrategy, HybridRetrievalStrategy)


class _Embedder:
    def embed_batch(self, texts):
        return [[1.0, 0.0] for _ in texts]


class _Sparse:
    def __init__(self):
        self.calls = 0

    def embed_batch(self, texts):
        self.calls += 1
        return [{1: 1.0} for _ in texts]


class _TextSparseVectors:
    sparse_input = "text"

    def __init__(self):
        self.received = None

    def hybrid_search(self, dense, sparse, *, top_k, filter=""):
        self.received = sparse
        return []


class _VectorSparseVectors:
    def __init__(self):
        self.received = None

    def hybrid_search(self, dense, sparse, *, top_k, filter=""):
        self.received = sparse
        return []


def test_text_sparse_backend_receives_raw_query():
    sparse = _Sparse()
    vectors = _TextSparseVectors()
    HybridRetrievalStrategy(_Embedder(), sparse, vectors).retrieve("黄河泥沙", 5)
    assert vectors.received == "黄河泥沙"
    assert sparse.calls == 0


def test_vector_sparse_backend_uses_sparse_embedder():
    sparse = _Sparse()
    vectors = _VectorSparseVectors()
    HybridRetrievalStrategy(_Embedder(), sparse, vectors).retrieve("黄河泥沙", 5)
    assert vectors.received == {1: 1.0}
    assert sparse.calls == 1


def test_vector_sparse_backend_requires_embedder():
    with pytest.raises(ValueError, match="稀疏向量生成器"):
        HybridRetrievalStrategy(_Embedder(), None, _VectorSparseVectors()).retrieve("问题", 5)


def test_backend_without_hybrid_search_rejected():
    with pytest.raises(ValueError, match="混合检索"):
        HybridRetrievalStrategy(_Embedder(), _Sparse(), object()).retrieve("问题", 5)
