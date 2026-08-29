"""与后端无关的候选检索策略。"""
from ..domain.models import VectorSearchRequest


class DenseRetrievalStrategy:
    def __init__(self, embedder, vectors, *, candidate_limit=100, multiplier=5):
        self.embedder = embedder
        self.vectors = vectors
        self.candidate_limit = candidate_limit
        self.multiplier = multiplier

    def retrieve(self, query: str, top_k: int, filter: str = ""):
        vector = self.embedder.embed_batch([query])[0]
        candidates = min(self.candidate_limit, max(top_k, top_k * self.multiplier))
        request = VectorSearchRequest(tuple(vector), top_k=candidates)
        search_request = getattr(self.vectors, "search_request", None)
        if callable(search_request) and not filter:
            return search_request(request)
        return self.vectors.search(vector, top_k=candidates, filter=filter)


class HybridRetrievalStrategy:
    def __init__(self, embedder, sparse_embedder, vectors, *, candidate_limit=100,
                 multiplier=5):
        self.embedder = embedder
        self.sparse_embedder = sparse_embedder
        self.vectors = vectors
        self.candidate_limit = candidate_limit
        self.multiplier = multiplier

    def retrieve(self, query: str, top_k: int, filter: str = ""):
        search = getattr(self.vectors, "hybrid_search", None)
        if not callable(search):
            raise ValueError("向量库不支持混合检索")
        dense = self.embedder.embed_batch([query])[0]
        candidates = min(self.candidate_limit, max(top_k, top_k * self.multiplier))
        # 服务端全文检索（BM25）后端：稀疏腿直接传查询原文，
        # 分词与加权由向量库完成，不经客户端稀疏生成器。
        if getattr(self.vectors, "sparse_input", "vector") == "text":
            request = VectorSearchRequest(tuple(dense), top_k=candidates, sparse_text=query)
            search_request = getattr(self.vectors, "search_request", None)
            if callable(search_request) and not filter:
                return search_request(request)
            return search(dense, query, top_k=candidates, filter=filter)
        if self.sparse_embedder is None:
            raise ValueError("未配置稀疏向量生成器")
        sparse = self.sparse_embedder.embed_batch([query])[0]
        request = VectorSearchRequest(
            tuple(dense), tuple(sparse.items()), top_k=candidates
        )
        search_request = getattr(self.vectors, "search_request", None)
        if callable(search_request) and not filter:
            return search_request(request)
        return search(dense, sparse, top_k=candidates, filter=filter)
