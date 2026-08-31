"""与后端无关的候选检索策略。"""
import time

import structlog

logger = structlog.get_logger(__name__)


class DenseRetrievalStrategy:
    def __init__(self, embedder, vectors, *, candidate_limit=100):
        self.embedder = embedder
        self.vectors = vectors
        self.candidate_limit = candidate_limit

    def retrieve(self, query: str, top_k: int, filter: str = ""):
        started = time.perf_counter()
        vector = self.embedder.embed_batch([query])[0]
        candidates = min(self.candidate_limit, top_k)
        rows = self.vectors.search(vector, top_k=candidates, filter=filter)
        logger.info("retrieve_dense_done", top_k=top_k, candidates=candidates,
                    returned=len(rows),
                    elapsed_seconds=round(time.perf_counter() - started, 3))
        return rows


class LexicalRetrievalStrategy:
    def __init__(self, lexical, *, candidate_limit=100):
        self.lexical = lexical
        self.candidate_limit = candidate_limit

    def retrieve(self, query: str, top_k: int, filter: str = ""):
        started = time.perf_counter()
        candidates = min(self.candidate_limit, top_k)
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