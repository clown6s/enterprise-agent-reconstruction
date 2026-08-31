"""Adapt the ingestion retriever into the chat DocumentRetriever port.

This wrapper is the only place chat is aware of ingestion's retrieve API.
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
