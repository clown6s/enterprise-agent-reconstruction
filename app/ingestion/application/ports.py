"""Ports used by ingestion use cases; implementations live outside application."""
from typing import Protocol, Sequence
from ..domain.models import ChunkRecord, DocumentSource, IngestionResult, OcrTask, ParsedDocument


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


class MetadataStore(Protocol):
    def find_by_sha(self, digest: str) -> dict | None: ...
    def record(self, digest: str, document_id: str, source: DocumentSource, chunks: int) -> None: ...


class OriginalFileStore(Protocol):
    def archive(self, digest: str, source: DocumentSource) -> None: ...


class EventPublisher(Protocol):
    def publish(self, event: dict) -> None: ...
