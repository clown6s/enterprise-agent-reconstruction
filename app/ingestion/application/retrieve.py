"""文档向量检索用例。"""
from dataclasses import dataclass
from typing import Any, Callable

import structlog

from .ports import Embedder
from .retrieval_strategies import (DenseRetrievalStrategy, HybridRetrievalStrategy,
                                  LexicalRetrievalStrategy)

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class RetrievalResult:
    """单条召回结果及其来源信息。"""
    text: str
    score: float
    document_id: str
    chunk_id: str | None = None
    page: int | None = None
    kind: str | None = None
    section_path: tuple[str, ...] = ()
    metadata: dict[str, Any] | None = None


class RetrieveDocuments:
    """使用与入库相同的 Embedder 和向量库检索文档。

    execute_hybrid() 使用 Milvus dense + Elasticsearch 全文检索并做 RRF 融合，
    是唯一的查询入口。
    """

    def __init__(self, embedder: Embedder, vectors,
                 metrics: Callable[[dict], None] | None = None,
                 dense_strategy=None, hybrid_strategy=None, lexical_strategy=None,
                 lexical=None, reranker=None, rerank_pool: int = 100):
        self.embedder = embedder
        self.vectors = vectors
        self.metrics = metrics
        self.dense_strategy = dense_strategy or DenseRetrievalStrategy(embedder, vectors)
        self.hybrid_strategy = hybrid_strategy or (
            HybridRetrievalStrategy(embedder, vectors, lexical))
        self.lexical_strategy = lexical_strategy or (
            LexicalRetrievalStrategy(lexical) if lexical is not None else None)
        self.reranker = reranker
        self.rerank_pool = max(1, int(rerank_pool))

    def execute_hybrid(self, query: str, *, top_k: int = 10,
                       filter: str = "") -> list[RetrievalResult]:
        """执行 Milvus dense + Elasticsearch 全文检索的混合检索。"""
        query, top_k = self._validate(query, top_k)
        if not query:
            return []
        if self.lexical_strategy is None:
            raise ValueError("未配置全文检索存储")
        candidates = self.rerank_pool if self.reranker is not None else top_k
        rows = self.hybrid_strategy.retrieve(query, candidates, filter)
        rows = self._rerank(query, self._dedup(rows))
        self._emit_metrics(len(rows), len(rows[:top_k]), top_k)
        return self._results(rows[:top_k])

    @staticmethod
    def _validate(query: str, top_k: int):
        if not isinstance(query, str):
            raise TypeError("query 必须是字符串")
        query = query.strip()
        if not query:
            return "", top_k
        if not isinstance(top_k, int) or isinstance(top_k, bool) or not 1 <= top_k <= 100:
            raise ValueError("top_k 必须是 1 到 100 之间的整数")
        return query, top_k

    @staticmethod
    def _dedup(rows):
        """按 chunk 身份去重，保留首次出现（分数最高）的一条。"""
        unique = {}
        for row in rows:
            key = row.get("chunk_id") or (row.get("document_id"), row.get("page"), row.get("text", ""))
            if key not in unique:
                unique[key] = row
        return list(unique.values())

    def _rerank(self, query: str, rows):
        """用模型对候选重排序；无 reranker 或调用失败时退回原序。"""
        if self.reranker is None or not rows:
            return rows
        texts = [str(row.get("text", "") or "") for row in rows]
        try:
            ranked = self.reranker.rerank(query, texts, top_n=len(rows))
        except Exception as exc:  # 第三方接口失败不拖垮查询，退回召回序
            logger.warning("rerank_failed_fallback_to_retrieval_order",
                           error=str(exc), candidates=len(rows))
            return rows
        ordered = []
        for index, score in ranked:
            item = dict(rows[index])
            item["score"] = float(score)
            ordered.append(item)
        return ordered

    def _emit_metrics(self, candidates, returned, top_k):
        if self.metrics:
            self.metrics({"candidate_count": candidates,
                          "returned_count": returned, "top_k": top_k})

    @staticmethod
    def _results(rows):
        return [RetrievalResult(
            text=row.get("text", ""), score=float(row.get("score", 0)),
            document_id=row.get("document_id", ""), chunk_id=row.get("chunk_id"),
            page=row.get("page"),
            kind=row.get("kind"), section_path=_section_path(row.get("section_path")),
            metadata=row,
        ) for row in rows]


def _section_path(value) -> tuple[str, ...]:
    if isinstance(value, str):
        import json
        try:
            value = json.loads(value)
        except (ValueError, TypeError):
            return (value,) if value else ()
    return tuple(value or ())
