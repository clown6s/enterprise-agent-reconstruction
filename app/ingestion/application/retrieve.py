"""文档向量检索用例。"""
from dataclasses import dataclass
from typing import Any

from .ports import Embedder


@dataclass(frozen=True)
class RetrievalResult:
    """单条召回结果及其来源信息。"""
    text: str
    score: float
    document_id: str
    page: int | None = None
    kind: str | None = None
    section_path: tuple[str, ...] = ()
    metadata: dict[str, Any] | None = None


class RetrieveDocuments:
    """使用与入库相同的 Embedder 和向量库检索文档。

    mode="dense" 使用稠密检索（默认）；
    mode="hybrid" 同时使用稠密 + 稀疏向量并做 RRF 融合。
    """

    def __init__(self, embedder: Embedder, vectors, sparse_embedder=None):
        self.embedder = embedder
        self.vectors = vectors
        self.sparse_embedder = sparse_embedder

    def execute(self, query: str, *, top_k: int = 10,
                filter: str = "") -> list[RetrievalResult]:
        """执行稠密向量检索。"""
        query, top_k = self._validate(query, top_k)
        if not query:
            return []
        vector = self.embedder.embed_batch([query])[0]
        rows = self.vectors.search(vector, top_k=top_k, filter=filter)
        return self._results(rows)

    def execute_hybrid(self, query: str, *, top_k: int = 10,
                       filter: str = "") -> list[RetrievalResult]:
        """执行稠密 + 稀疏向量的混合检索。"""
        query, top_k = self._validate(query, top_k)
        if not query:
            return []
        if self.sparse_embedder is None:
            raise ValueError("未配置稀疏向量生成器")
        hybrid_search = getattr(self.vectors, "hybrid_search", None)
        if not callable(hybrid_search):
            raise ValueError("向量库不支持混合检索")
        dense = self.embedder.embed_batch([query])[0]
        sparse = self.sparse_embedder.embed_batch([query])[0]
        rows = hybrid_search(dense, sparse, top_k=top_k, filter=filter)
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
    def _results(rows):
        return [RetrievalResult(
            text=row.get("text", ""), score=float(row.get("score", 0)),
            document_id=row.get("document_id", ""), page=row.get("page"),
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
