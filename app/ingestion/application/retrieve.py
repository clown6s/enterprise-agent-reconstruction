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
    """使用与入库相同的 Embedder 和向量库检索文档。"""

    def __init__(self, embedder: Embedder, vectors):
        self.embedder = embedder
        self.vectors = vectors

    def execute(self, query: str, *, top_k: int = 10,
                filter: str = "") -> list[RetrievalResult]:
        query = query.strip()
        if not query:
            return []
        if top_k < 1:
            raise ValueError("top_k 必须大于 0")
        vector = self.embedder.embed_batch([query])[0]
        rows = self.vectors.search(vector, top_k=top_k, filter=filter)
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
