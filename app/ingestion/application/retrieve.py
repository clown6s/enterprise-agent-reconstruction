"""文档向量检索用例。"""
import os
from dataclasses import dataclass
from typing import Any, Callable

import structlog

from .ports import Embedder
from .retrieval_strategies import DenseRetrievalStrategy, LexicalRetrievalStrategy, _rrf

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


@dataclass(frozen=True)
class HybridStages:
    """一次 hybrid 查询的各阶段结果，供查询与审核工作台复用。"""
    milvus: list[dict]
    es: list[dict]
    rrf: list[dict]
    rerank: list[dict]
    rerank_status: str = "skipped"  # reranked | fallback | skipped


class RetrieveDocuments:
    """使用与入库相同的 Embedder 和向量库检索文档。

    execute_hybrid() 使用 Milvus dense + Elasticsearch 全文检索并做 RRF 融合，
    是唯一的查询入口。
    """

    def __init__(self, embedder: Embedder, vectors,
                 metrics: Callable[[dict], None] | None = None,
                 dense_strategy=None, lexical_strategy=None,
                 lexical=None, reranker=None,
                 recall_k: int | None = None, rerank_k: int | None = None):
        self.embedder = embedder
        self.vectors = vectors
        self.metrics = metrics
        self.dense_strategy = dense_strategy or DenseRetrievalStrategy(embedder, vectors)
        self.lexical_strategy = lexical_strategy or (
            LexicalRetrievalStrategy(lexical) if lexical is not None else None)
        self.reranker = reranker
        self.recall_k = max(1, int(recall_k if recall_k is not None
                                   else os.getenv("RECALL_K", "100")))
        self.rerank_k = max(1, int(rerank_k if rerank_k is not None
                                   else os.getenv("RERANK_K", "100")))
        self.rerank_k = min(self.rerank_k, self.recall_k)  # rerank 池不能超过召回池

    def hybrid_stages(self, query: str, *, filter: str = "") -> HybridStages:
        """执行一次完整 hybrid 查询并保留各阶段结果。"""
        if not isinstance(query, str):
            raise TypeError("query 必须是字符串")
        query = query.strip()
        if not query:
            return HybridStages([], [], [], [], "skipped")
        if self.lexical_strategy is None:
            raise ValueError("未配置全文检索存储")
        dense_rows = self.dense_strategy.retrieve(query, self.recall_k, filter)
        lexical_rows = self.lexical_strategy.retrieve(query, self.recall_k, filter)
        fused_rows = _rrf(dense_rows, lexical_rows)
        deduped_rows = self._dedup(fused_rows)
        pool_rows = deduped_rows[:self.rerank_k]  # 只送 RERANK_K 给 rerank
        reranked_rows, rerank_status = self._rerank(query, pool_rows)
        return HybridStages(dense_rows, lexical_rows, fused_rows, reranked_rows,
                            rerank_status)

    def execute_hybrid(self, query: str, *, top_k: int = 10,
                       filter: str = "") -> list[RetrievalResult]:
        """执行完整 hybrid 检索并返回最终 Top-K。"""
        query, top_k = self._validate(query, top_k)
        stages = self.hybrid_stages(query, filter=filter)
        if not query:
            return []
        rows = stages.rerank[:top_k]
        self._emit_metrics(len(stages.rrf), len(rows), top_k)
        return self._results(rows)

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
        """用模型对候选重排序；自行按分数降序排，不依赖适配器返回有序。

        返回 (排序后的 rows, 状态)。无 reranker / 为空返回 ("skipped")，
        调用失败退回召回序并标记 "fallback"。
        """
        if self.reranker is None or not rows:
            return rows, "skipped"
        texts = [str(row.get("text", "") or "") for row in rows]
        try:
            ranked = self.reranker.rerank(query, texts, top_n=len(rows))
            scored = []
            seen_indexes = set()
            for item in ranked:
                if not isinstance(item, (tuple, list)) or len(item) != 2:
                    raise ValueError("reranker 返回了无效数据项")
                index, score = item
                if (isinstance(index, bool) or not isinstance(index, int)
                        or not 0 <= index < len(rows) or index in seen_indexes):
                    raise ValueError("reranker 返回了无效候选下标")
                seen_indexes.add(index)
                scored_item = dict(rows[index])
                scored_item["score"] = float(score)
                scored.append((float(score), scored_item))
            if len(scored) != len(rows):
                raise ValueError("reranker 返回数量不完整")
        except Exception as exc:  # 第三方接口或响应异常不拖垮查询，退回召回序
            logger.warning("rerank_failed_fallback_to_retrieval_order",
                           error=str(exc), candidates=len(rows))
            return rows, "fallback"
        ordered = [item for _, item in sorted(scored, key=lambda pair: pair[0],
                                              reverse=True)]
        return ordered, "reranked"

    def close(self):
        """释放 reranker 持有的外部客户端。"""
        close = getattr(self.reranker, "close", None)
        if callable(close):
            close()

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
