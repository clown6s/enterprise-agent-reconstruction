"""持久化协调与尽力而为的补偿处理。"""
import time

import structlog

logger = structlog.get_logger(__name__)


class IngestionPersistence:
    """严格双写：Milvus 与 Elasticsearch 任一失败都不算成功，并补偿已成功一侧。"""

    def __init__(self, vectors, metadata, lexical=None):
        self.vectors = vectors
        self.metadata = metadata
        self.lexical = lexical

    def persist(self, rows, digest, document_id, source, chunk_count):
        vector_written = False
        lexical_written = False
        # 本次写入的 chunk 集合：补偿时按 chunk_id 精确回滚，避免误删同文档其他批次。
        chunk_ids = [row["chunk_id"] for row in rows if row.get("chunk_id")]
        try:
            started = time.perf_counter()
            logger.info("persist_milvus_start", document_id=document_id, row_count=len(rows))
            if not self.vectors.insert(rows):
                raise RuntimeError("向量库写入失败")
            vector_written = True
            logger.info("persist_milvus_done", document_id=document_id,
                        row_count=len(rows),
                        elapsed_seconds=round(time.perf_counter() - started, 3))
            if self.lexical is not None:
                # 即使 bulk 部分失败才抛异常，也按已写入标记补偿删除。
                lexical_written = True
                started = time.perf_counter()
                logger.info("persist_es_start", document_id=document_id, row_count=len(rows))
                if not self.lexical.upsert(rows):
                    raise RuntimeError("全文库写入失败")
                logger.info("persist_es_done", document_id=document_id,
                            row_count=len(rows),
                            elapsed_seconds=round(time.perf_counter() - started, 3))
            started = time.perf_counter()
            self.metadata.record(digest, document_id, source, chunk_count)
            logger.info("persist_metadata_done", document_id=document_id,
                        elapsed_seconds=round(time.perf_counter() - started, 3))
        except Exception as exc:
            cleanup_errors = []
            if lexical_written:
                try:
                    delete_chunks = getattr(self.lexical, "delete_chunks", None)
                    if chunk_ids and callable(delete_chunks):
                        delete_chunks(chunk_ids)
                    else:
                        # 兼容未实现 delete_chunks 的实现，回退到整文档删除。
                        self.lexical.delete(document_id)
                except Exception as cleanup_exc:
                    cleanup_errors.append(f"全文库补偿删除失败:{type(cleanup_exc).__name__}")
            if vector_written:
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