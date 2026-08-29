"""与后端无关的候选检索策略。"""


class DenseRetrievalStrategy:
    def __init__(self, embedder, vectors, *, candidate_limit=100, multiplier=5):
        self.embedder = embedder
        self.vectors = vectors
        self.candidate_limit = candidate_limit
        self.multiplier = multiplier

    def retrieve(self, query: str, top_k: int, filter: str = ""):
        vector = self.embedder.embed_batch([query])[0]
        candidates = min(self.candidate_limit, max(top_k, top_k * self.multiplier))
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
        if self.sparse_embedder is None:
            raise ValueError("未配置稀疏向量生成器")
        search = getattr(self.vectors, "hybrid_search", None)
        if not callable(search):
            raise ValueError("向量库不支持混合检索")
        dense = self.embedder.embed_batch([query])[0]
        sparse = self.sparse_embedder.embed_batch([query])[0]
        candidates = min(self.candidate_limit, max(top_k, top_k * self.multiplier))
        return search(dense, sparse, top_k=candidates, filter=filter)
