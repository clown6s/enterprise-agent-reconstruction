"""文档向量检索用例。"""
import os
from dataclasses import dataclass
from typing import Any, Callable

from .ports import Embedder
from .query_analysis import QueryProfile, analyze_query
from .retrieval_strategies import (DenseRetrievalStrategy, HybridRetrievalStrategy,
                                  LexicalRetrievalStrategy)
from .retrieval_router import DefaultRetrievalRouter


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

    mode="dense" 使用稠密检索（默认）；
    execute() 使用 Milvus dense 检索；
    execute_hybrid() 使用 Milvus dense + Elasticsearch 全文检索并做 RRF 融合。
    """

    def __init__(self, embedder: Embedder, vectors,
                 metrics: Callable[[dict], None] | None = None,
                 dense_strategy=None, hybrid_strategy=None, lexical_strategy=None,
                 router=None, lexical=None):
        self.embedder = embedder
        self.vectors = vectors
        self.metrics = metrics
        self.dense_strategy = dense_strategy or DenseRetrievalStrategy(embedder, vectors)
        self.hybrid_strategy = hybrid_strategy or (
            HybridRetrievalStrategy(embedder, vectors, lexical))
        self.lexical_strategy = lexical_strategy or (
            LexicalRetrievalStrategy(lexical) if lexical is not None else None)
        self.router = router or DefaultRetrievalRouter()

    def execute(self, query: str, *, top_k: int = 10,
                filter: str = "") -> list[RetrievalResult]:
        """执行稠密向量检索。"""
        query, top_k = self._validate(query, top_k)
        if not query:
            return []
        profile = analyze_query(query)
        rows = self.dense_strategy.retrieve(query, top_k, filter)
        rows = self._rank(rows, profile)
        self._emit_metrics(profile, len(rows), len(rows[:top_k]), top_k)
        return self._results(rows[:top_k])

    def execute_hybrid(self, query: str, *, top_k: int = 10,
                       filter: str = "") -> list[RetrievalResult]:
        """执行 Milvus dense + Elasticsearch 全文检索的混合检索。"""
        query, top_k = self._validate(query, top_k)
        if not query:
            return []
        profile = analyze_query(query)
        if self.lexical_strategy is None:
            raise ValueError("未配置全文检索存储")
        rows = self.hybrid_strategy.retrieve(
            query, top_k, filter,
            lexical_weight=self._lexical_weight(profile.kind),
        )
        rows = self._rank(rows, profile)
        self._emit_metrics(profile, len(rows), len(rows[:top_k]), top_k)
        return self._results(rows[:top_k])

    @staticmethod
    def _lexical_weight(kind: str) -> float:
        """按 query 类型返回 ES 融合权重；三档默认值可用环境变量覆盖。"""
        weights = {
            "exact": float(os.getenv("ES_LEXICAL_WEIGHT_EXACT", "0.50")),
            "section": float(os.getenv("ES_LEXICAL_WEIGHT_SECTION", "0.35")),
            "semantic": float(os.getenv("ES_LEXICAL_WEIGHT_SEMANTIC", "0.05")),
        }
        return weights.get(kind, weights["semantic"])

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

    @classmethod
    def _rank(cls, rows, profile: QueryProfile):
        ranked = []
        for row in cls._dedup(rows):
            text = " ".join(str(row.get(name, "")) for name in ("text", "search_text", "article", "section_path")).lower()
            score = float(row.get("score", 0.0))
            score += min(0.05 * sum(term.lower() in text for term in profile.exact_terms), 0.20)
            score += min(0.05 * sum(term.lower() in text for term in profile.section_terms), 0.10)
            item = dict(row); item["score"] = score
            ranked.append(item)
        return sorted(ranked, key=lambda row: row["score"], reverse=True)

    def _emit_metrics(self, profile, candidates, returned, top_k):
        if self.metrics:
            self.metrics({"query_type": profile.kind, "candidate_count": candidates,
                          "returned_count": returned, "top_k": top_k,
                          "exact_term_count": len(profile.exact_terms),
                          "section_term_count": len(profile.section_terms)})

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
