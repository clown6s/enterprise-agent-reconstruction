"""Upload use case. It has no framework or infrastructure imports."""
from dataclasses import replace
import threading

from ..domain.models import DocumentSource, IngestionResult, IngestionStatus, OcrStatus
from ..domain.policies import document_title, sha256, validate_size
from .ports import Classifier, ChunkerSelector, Embedder, EventPublisher, MetadataStore, OriginalFileStore, OcrProvider, Parser, VectorStore


class IngestDocument:
    def __init__(self, parser: Parser, classifier: Classifier, chunker: ChunkerSelector,
                 embedder: Embedder, vectors: VectorStore, metadata: MetadataStore,
                 originals: OriginalFileStore, sparse_embedder=None, ocr: OcrProvider | None = None,
                 events: EventPublisher | None = None, max_file_bytes: int = 50 * 1024 * 1024):
        self.parser, self.classifier, self.chunker = parser, classifier, chunker
        self.embedder, self.vectors, self.metadata = embedder, vectors, metadata
        self.sparse_embedder = sparse_embedder
        self.originals, self.ocr, self.events = originals, ocr, events
        self.max_file_bytes = max_file_bytes
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
                    self.originals.archive(digest, source)
                    return IngestionResult(IngestionStatus.DUPLICATE, filename, source.size, existing.get("docId"), existing.get("chunks", 0))
            existing = self.metadata.find_by_sha(digest)
            existing_document_id = existing.get("docId") if existing else None
            if existing_document_id and self.vectors.has_document(existing_document_id):
                self.originals.archive(digest, source)
                return IngestionResult(IngestionStatus.DUPLICATE, filename, source.size, existing_document_id, existing.get("chunks", 0))
        try:
            parsed = self.parser.parse(source)
            kind = self.classifier.classify(parsed, source)
            parsed = replace(parsed, profile=kind)
            if self.ocr and kind == "technical_book":
                task = self.ocr.create_or_get(source)
                if task.status != OcrStatus.SUCCESS:
                    return IngestionResult(IngestionStatus.PENDING, filename, source.size, task_id=task.task_id, ocr_status=task.status)
                parsed = task.parsed or parsed
                kind = self.classifier.classify(parsed, source)
                parsed = replace(parsed, profile=kind)
            if not parsed.text.strip():
                return IngestionResult(IngestionStatus.FAILED, filename, source.size, message=f"未从《{filename}》中解析出文本")
            chunks = self.chunker.chunk(kind, parsed, source)
            if not chunks:
                return IngestionResult(IngestionStatus.FAILED, filename, source.size, message=f"《{filename}》切分后无内容")
            vectors = self.embedder.embed_batch([chunk.text for chunk in chunks])
            sparse_vectors = (self.sparse_embedder.embed_batch([chunk.text for chunk in chunks])
                              if self.sparse_embedder else None)
            # 文档 ID 由内容摘要确定，重试时保持幂等。
            document_id = digest[:32]
            title = document_title(source.title, filename)
            rows = []
            for index, chunk in enumerate(chunks):
                row = {"text": chunk.text, "dense": vectors[index], "document_id": document_id, "title": title, "source": title, "page": chunk.page, "kind": chunk.kind, "section_path": list(chunk.section_path), "continuation": chunk.continuation, "continuation_of": chunk.continuation_of, "continuation_index": chunk.continuation_index}
                if sparse_vectors is not None:
                    row["sparse"] = sparse_vectors[index]
                row.update(chunk.metadata)
                rows.append(row)
            inserted = False
            try:
                inserted = True
                if not self.vectors.insert(rows):
                    raise RuntimeError("向量库写入失败")
                self.metadata.record(digest, document_id, source, len(chunks))
            except Exception as exc:
                if inserted:
                    cleanup_errors = []
                    try:
                        self.vectors.delete(document_id)
                    except Exception as cleanup_exc:
                        cleanup_errors.append(f"向量补偿删除失败:{type(cleanup_exc).__name__}")
                    try:
                        mark_failed = getattr(self.metadata, "mark_failed", None)
                        if callable(mark_failed):
                            mark_failed(digest, document_id)
                    except Exception as status_exc:
                        cleanup_errors.append(f"失败状态记录失败:{type(status_exc).__name__}")
                    if cleanup_errors:
                        raise RuntimeError("；".join(cleanup_errors)) from exc
                raise
            self.originals.archive(digest, source)
            if self.events:
                self.events.publish({"type": "DocumentIngested", "document_id": document_id, "sha256": digest, "filename": filename})
            return IngestionResult(IngestionStatus.INGESTED, filename, source.size, document_id, len(chunks), diagnostics=parsed.diagnostics)
        except Exception as exc:
            return IngestionResult(IngestionStatus.FAILED, filename, source.size, message=f"《{filename}》摄入失败：{type(exc).__name__}")
