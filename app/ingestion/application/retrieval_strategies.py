"""与后端无关的候选检索策略。"""
import time

import structlog

logger = structlog.get_logger(__name__)


class DenseRetrievalStrategy:
    def __init__(self, embedder, vectors, *, candidate_limit=100, multiplier=5):
        self.embedder = embedder
        self.vectors = vectors
        self.candidate_limit = candidate_limit
        self.multiplier = multiplier

    def retrieve(self, query: str, top_k: int, filter: str = ""):
        started = time.perf_counter()
        vector = self.embedder.embed_batch([query])[0]
        candidates = min(self.candidate_limit, max(top_k, top_k * self.multiplier))
        rows = self.vectors.search(vector, top_k=candidates, filter=filter)
        logger.info("retrieve_dense_done", top_k=top_k, candidates=candidates,
                    returned=len(rows),
                    elapsed_seconds=round(time.perf_counter() - started, 3))
        return rows


class LexicalRetrievalStrategy:
    def __init__(self, lexical, *, candidate_limit=100, multiplier=5):
        self.lexical = lexical
        self.candidate_limit = candidate_limit
        self.multiplier = multiplier

    def retrieve(self, query: str, top_k: int, filter: str = ""):
        started = time.perf_counter()
        candidates = min(self.candidate_limit, max(top_k, top_k * self.multiplier))
        rows = self.lexical.search(query, top_k=candidates, filter=filter)
        logger.info("retrieve_lexical_done", top_k=top_k, candidates=candidates,
                    returned=len(rows),
                    elapsed_seconds=round(time.perf_counter() - started, 3))
        return rows


def _rrf(dense_rows, lexical_rows, rrf_k=60, lexical_weight=1.0):
    fused = {}
    for source_rows, weight in ((dense_rows, 1.0), (lexical_rows, lexical_weight)):
        for rank, row in enumerate(source_rows, 1):
            key = row.get("chunk_id")
            if key is not None:
                item = fused.setdefault(key, dict(row))
                item.setdefault("_rrf_score", 0.0)
                item["_rrf_score"] += weight / (rrf_k + rank)
    for item in fused.values():
        item["score"] = item.pop("_rrf_score")
    return sorted(fused.values(), key=lambda row: row["score"], reverse=True)


class HybridRetrievalStrategy:
    """Milvus dense + Elasticsearch 全文检索，按 chunk_id 做 RRF 融合。"""
    def __init__(self, embedder, vectors, lexical=None, *, candidate_limit=100,
                 multiplier=5, lexical_weight=1.0):
        self.embedder = embedder
        self.vectors = vectors
        self.lexical = lexical
        self.candidate_limit = candidate_limit
        self.multiplier = multiplier
        self.lexical_weight = float(lexical_weight)
        if self.lexical_weight < 0:
            raise ValueError("lexical_weight 不能为负数")

    def retrieve(self, query: str, top_k: int, filter: str = "", *,
                 lexical_weight: float | None = None):
        if self.lexical is None:
            raise ValueError("未配置全文检索存储")
        started = time.perf_counter()
        dense = self.embedder.embed_batch([query])[0]
        candidates = min(self.candidate_limit, max(top_k, top_k * self.multiplier))
        dense_rows = self.vectors.search(dense, top_k=candidates, filter=filter)
        lexical_rows = self.lexical.search(query, top_k=candidates, filter=filter)
        weight = self.lexical_weight if lexical_weight is None else float(lexical_weight)
        if weight < 0:
            raise ValueError("lexical_weight 不能为负数")
        fused = _rrf(dense_rows, lexical_rows, lexical_weight=weight)
        logger.info("retrieve_hybrid_done", top_k=top_k, candidates=candidates,
                    dense=len(dense_rows), lexical=len(lexical_rows),
                    returned=len(fused),
                    elapsed_seconds=round(time.perf_counter() - started, 3))
        return fused