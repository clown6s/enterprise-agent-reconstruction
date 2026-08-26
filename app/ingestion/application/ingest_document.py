"""Upload use case. It has no framework or infrastructure imports."""
import uuid
from dataclasses import replace

from ..domain.models import DocumentSource, IngestionResult, IngestionStatus, OcrStatus
from ..domain.policies import document_title, sha256, validate_size
from .ports import Classifier, ChunkerSelector, Embedder, EventPublisher, MetadataStore, OriginalFileStore, OcrProvider, Parser, VectorStore


class IngestDocument:
    def __init__(self, parser: Parser, classifier: Classifier, chunker: ChunkerSelector,
                 embedder: Embedder, vectors: VectorStore, metadata: MetadataStore,
                 originals: OriginalFileStore, ocr: OcrProvider | None = None,
                 events: EventPublisher | None = None, max_file_bytes: int = 50 * 1024 * 1024):
        self.parser, self.classifier, self.chunker = parser, classifier, chunker
        self.embedder, self.vectors, self.metadata = embedder, vectors, metadata
        self.originals, self.ocr, self.events = originals, ocr, events
        self.max_file_bytes = max_file_bytes

    def execute(self, source: DocumentSource) -> IngestionResult:
        filename = source.filename or "未命名"
        try:
            validate_size(source.size, self.max_file_bytes)
        except ValueError as exc:
            return IngestionResult(IngestionStatus.REJECTED, filename, source.size, message=str(exc))
        digest = sha256(source.content)
        existing = self.metadata.find_by_sha(digest)
        if existing and self.vectors.has_document(existing.get("docId", "")):
            self.originals.archive(digest, source)
            return IngestionResult(IngestionStatus.DUPLICATE, filename, source.size, existing.get("docId"), existing.get("chunks", 0))
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
            document_id = uuid.uuid4().hex
            title = document_title(source.title, filename)
            rows = []
            for index, chunk in enumerate(chunks):
                row = {"text": chunk.text, "dense": vectors[index], "document_id": document_id, "title": title, "source": title, "page": chunk.page, "kind": chunk.kind, "section_path": list(chunk.section_path), "continuation": chunk.continuation, "continuation_of": chunk.continuation_of, "continuation_index": chunk.continuation_index}
                row.update(chunk.metadata)
                rows.append(row)
            if not self.vectors.insert(rows):
                return IngestionResult(IngestionStatus.FAILED, filename, source.size, message=f"《{filename}》向量库写入失败")
            self.metadata.record(digest, document_id, source, len(chunks))
            self.originals.archive(digest, source)
            if self.events:
                self.events.publish({"type": "DocumentIngested", "document_id": document_id, "sha256": digest, "filename": filename})
            return IngestionResult(IngestionStatus.INGESTED, filename, source.size, document_id, len(chunks), diagnostics=parsed.diagnostics)
        except Exception as exc:
            return IngestionResult(IngestionStatus.FAILED, filename, source.size, message=f"《{filename}》摄入失败：{type(exc).__name__}")
