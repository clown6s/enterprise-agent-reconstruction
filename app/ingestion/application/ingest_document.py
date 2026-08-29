"""Upload use case. It has no framework or infrastructure imports."""
from dataclasses import replace
import threading

from ..domain.models import DocumentSource, IngestionResult, IngestionStatus, OcrStatus
from ..domain.policies import document_title, sha256, validate_size
from .ports import Classifier, ChunkerSelector, Embedder, EventPublisher, MetadataStore, OcrProvider, Parser, VectorStore


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
                 events: EventPublisher | None = None, max_file_bytes: int = 50 * 1024 * 1024):
        self.parser, self.classifier, self.chunker = parser, classifier, chunker
        self.embedder, self.vectors, self.metadata = embedder, vectors, metadata
        self.sparse_embedder = sparse_embedder
        self.ocr, self.events = ocr, events
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
                    return IngestionResult(IngestionStatus.DUPLICATE, filename, source.size, existing.get("docId"), existing.get("chunks", 0))
            existing = self.metadata.find_by_sha(digest)
            existing_document_id = existing.get("docId") if existing else None
            if existing_document_id and self.vectors.has_document(existing_document_id):
                    return IngestionResult(IngestionStatus.DUPLICATE, filename, source.size, existing_document_id, existing.get("chunks", 0))
        try:
            parsed = self.parser.parse(source)
            kind = self.classifier.classify(parsed, source)
            profile_parser = getattr(self.parser, "for_profile", lambda profile: self.parser)(kind)
            if profile_parser is not self.parser:
                parsed = profile_parser.parse(source)
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
            search_texts = [_search_text(chunk) for chunk in chunks]
            vectors = self.embedder.embed_batch(search_texts)
            if not isinstance(vectors, list) or len(vectors) != len(chunks):
                raise ValueError("dense embedding 数量必须与 chunk 数量一致")
            if any(not isinstance(vector, (list, tuple)) or not vector for vector in vectors):
                raise ValueError("dense embedding 向量格式无效")
            sparse_vectors = (self.sparse_embedder.embed_batch(search_texts)
                              if self.sparse_embedder else None)
            if sparse_vectors is not None and (
                not isinstance(sparse_vectors, list) or len(sparse_vectors) != len(chunks)
            ):
                raise ValueError("sparse embedding 数量必须与 chunk 数量一致")
            # 文档 ID 由内容摘要确定，重试时保持幂等。
            document_id = digest[:32]
            title = document_title(source.title, filename)
            rows = []
            for index, chunk in enumerate(chunks):
                row = {"text": chunk.text, "search_text": search_texts[index], "dense": vectors[index], "document_id": document_id, "title": title, "source": title, "page": chunk.page, "page_end": chunk.page_end, "kind": chunk.kind, "section_path": list(chunk.section_path), "chunk_role": chunk.metadata.get("chunk_role", chunk.kind), "continuation": chunk.continuation, "continuation_of": chunk.continuation_of, "continuation_index": chunk.continuation_index}
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
            if self.events:
                try:
                    self.events.publish({"type": "DocumentIngested", "document_id": document_id, "sha256": digest, "filename": filename})
                except Exception:
                    # 数据已持久化；事件失败不应把成功入库报告为失败。
                    pass
            return IngestionResult(IngestionStatus.INGESTED, filename, source.size, document_id, len(chunks), diagnostics=parsed.diagnostics)
        except Exception as exc:
            return IngestionResult(IngestionStatus.FAILED, filename, source.size, message=f"《{filename}》摄入失败：{type(exc).__name__}")
