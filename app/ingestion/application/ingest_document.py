"""文档摄入用例，不依赖框架或基础设施实现。"""
from dataclasses import replace
import threading

from ..domain.models import DocumentSource, IngestionResult, IngestionStatus, OcrStatus
from ..domain.policies import document_title, sha256, validate_size
from .ports import Classifier, ChunkerSelector, Embedder, EventPublisher, MetadataStore, OcrProvider, Parser, VectorStore
from .document_preparation import DocumentPreparation
from .embedding_service import EmbeddingService
from .ingestion_persistence import IngestionPersistence
from .vector_row_factory import build_vector_rows


def _search_text(chunk) -> str:
    """为向量化补充章节/类别上下文，同时保留原始 chunk 文本。"""
    context = " > ".join(chunk.section_path)
    metadata = chunk.metadata
    if metadata.get("category"):
        context = f"{context} > {metadata['category']}" if context else metadata["category"]
    if metadata.get("question_number") is not None:
        context = f"{context} > 问题 {metadata['question_number']}" if context else f"问题 {metadata['question_number']}"
    return f"上下文：{context}\n{chunk.text}" if context else chunk.text


class IngestDocument:
    def __init__(self, parser: Parser, classifier: Classifier, chunker: ChunkerSelector,
                 embedder: Embedder, vectors: VectorStore, metadata: MetadataStore,
                 sparse_embedder=None, ocr: OcrProvider | None = None,
                 events: EventPublisher | None = None, max_file_bytes: int = 50 * 1024 * 1024,
                 embedding_dim: int | None = None):
        self.parser, self.classifier, self.chunker = parser, classifier, chunker
        self.embedder, self.vectors, self.metadata = embedder, vectors, metadata
        self.sparse_embedder = sparse_embedder
        self.ocr, self.events = ocr, events
        self.preparation = DocumentPreparation(parser, classifier, ocr)
        self.embedding_service = EmbeddingService(embedder, sparse_embedder, embedding_dim)
        self.persistence = IngestionPersistence(vectors, metadata)
        if embedding_dim is not None and embedding_dim <= 0:
            raise ValueError("embedding_dim 必须为正数")
        self.max_file_bytes = max_file_bytes
        self.embedding_dim = embedding_dim
        self._claims_lock = threading.Lock()

    def execute(self, source: DocumentSource) -> IngestionResult:
        filename = source.filename or "未命名"
        try:
            validate_size(source.size, self.max_file_bytes)
        except ValueError as exc:
            return IngestionResult(IngestionStatus.REJECTED, filename, source.size, message=str(exc))
        digest = sha256(source.content)
        with self._claims_lock:
            claim = getattr(self.metadata, "claim", None)
            if callable(claim) and not claim(digest, digest[:32], source):
                existing = self.metadata.find_by_sha(digest)
                if existing:
                    if existing.get("status") == "processing":
                        return IngestionResult(IngestionStatus.PENDING, filename, source.size, existing.get("docId"), existing.get("chunks", 0), message="文档正在由其他实例处理")
                    return IngestionResult(IngestionStatus.DUPLICATE, filename, source.size, existing.get("docId"), existing.get("chunks", 0))
            existing = self.metadata.find_by_sha(digest)
            existing_document_id = existing.get("docId") if existing else None
            if existing_document_id and self.vectors.has_document(existing_document_id):
                    return IngestionResult(IngestionStatus.DUPLICATE, filename, source.size, existing_document_id, existing.get("chunks", 0))
        try:
            parsed, kind, task = self.preparation.prepare(source)
            if task is not None:
                return IngestionResult(IngestionStatus.PENDING, filename, source.size, task_id=task.task_id, ocr_status=task.status)
            if not parsed.text.strip():
                return IngestionResult(IngestionStatus.FAILED, filename, source.size, message=f"未从《{filename}》中解析出文本")
            chunks = self.chunker.chunk(kind, parsed, source)
            if not chunks:
                return IngestionResult(IngestionStatus.FAILED, filename, source.size, message=f"《{filename}》切分后无内容")
            search_texts, vectors, sparse_vectors = self.embedding_service.embed(chunks)
            # 文档 ID 由内容摘要确定，重试时保持幂等。
            document_id = digest[:32]
            rows = build_vector_rows(
                chunks, search_texts, vectors, sparse_vectors, document_id, source
            )
            self.persistence.persist(rows, digest, document_id, source, len(chunks))
            if self.events:
                try:
                    self.events.publish({"type": "DocumentIngested", "document_id": document_id, "sha256": digest, "filename": filename})
                except Exception:
                    # 数据已持久化；事件失败不应把成功入库报告为失败。
                    pass
            return IngestionResult(IngestionStatus.INGESTED, filename, source.size, document_id, len(chunks), diagnostics=parsed.diagnostics)
        except Exception as exc:
            return IngestionResult(IngestionStatus.FAILED, filename, source.size, message=f"《{filename}》摄入失败：{type(exc).__name__}")
