"""将 ingestion 检索器适配为聊天应用的 DocumentRetriever 端口。

此包装器是聊天应用感知 ingestion 检索接口的唯一位置。
"""
from app.ingestion.application.retrieve import RetrieveDocuments

from ..application.ports import DocumentRetriever
from ..domain.models import RetrievalItem


class IngestionRetriever(DocumentRetriever):
    def __init__(self, retriever: RetrieveDocuments):
        self._retriever = retriever

    def retrieve(self, query: str, *, top_k: int = 5,
                 filter: str = "") -> list[RetrievalItem]:
        results = self._retriever.execute_hybrid(query, top_k=top_k, filter=filter)
        return [RetrievalItem(
            text=item.text, score=item.score, document_id=item.document_id,
            chunk_id=item.chunk_id, page=item.page,
            section_path=item.section_path, metadata=item.metadata or {},
        ) for item in results]

    def close(self) -> None:
        close = getattr(self._retriever, "close", None)
        if callable(close):
            close()
