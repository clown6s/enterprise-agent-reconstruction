"""数据摄取用例所使用的端口；实现位于应用程序外部."""
from typing import Protocol, Sequence
from ..domain.models import ChunkRecord, DocumentSource, OcrTask, ParsedDocument


class Parser(Protocol):
    def parse(self, source: DocumentSource) -> ParsedDocument: ...


class ImageTextExtractor(Protocol):
    def extract(self, image: bytes, *, filename: str, index: int) -> str: ...


class Classifier(Protocol):
    def classify(self, document: ParsedDocument, source: DocumentSource) -> str: ...


class Chunker(Protocol):
    def chunk(self, document: ParsedDocument, source: DocumentSource) -> list[ChunkRecord]: ...


class ChunkerSelector(Protocol):
    def chunk(self, kind: str, document: ParsedDocument,
              source: DocumentSource) -> list[ChunkRecord]: ...


class OcrProvider(Protocol):
    def create_or_get(self, source: DocumentSource) -> OcrTask: ...
    def query(self, task_id: str) -> OcrTask: ...


class Embedder(Protocol):
    def embed_batch(self, texts: Sequence[str]) -> list[list[float]]: ...


class VectorStore(Protocol):
    def has_document(self, document_id: str) -> bool: ...
    def insert(self, rows: list[dict]) -> bool: ...
    def delete(self, document_id: str) -> int: ...


class DenseSearcher(Protocol):
    def search(self, vector: list[float], *, top_k: int = 10,
               filter: str = "") -> list[dict]: ...


class HybridSearcher(Protocol):
    def hybrid_search(self, dense_vector: list[float], sparse_vector: dict[int, float],
                      *, top_k: int = 10, filter: str = "") -> list[dict]: ...


class SparseEmbedder(Protocol):
    def embed_batch(self, texts: Sequence[str]) -> list[dict[int, float]]: ...


class Reranker(Protocol):
    """cross-encoder 重排序：返回 (候选下标, 相关分)，按分数降序。"""
    def rerank(self, query: str, texts: Sequence[str], *,
               top_n: int) -> list[tuple[int, float]]: ...


class RetrievalRouter(Protocol):
    def route(self, profile, requested_mode: str) -> str: ...


class MetadataStore(Protocol):
    def find_by_sha(self, digest: str) -> dict | None: ...
    def find_by_document_id(self, document_id: str) -> dict | None: ...
    def record(self, digest: str, document_id: str, source: DocumentSource, chunks: int) -> None: ...
    def claim(self, digest: str, document_id: str, source: DocumentSource,
              stale_after: int = 1800) -> bool: ...
    def delete_by_document_id(self, document_id: str) -> int: ...
    def mark_failed(self, digest: str, document_id: str) -> None: ...


class EventPublisher(Protocol):
    def publish(self, event: dict) -> None: ...
