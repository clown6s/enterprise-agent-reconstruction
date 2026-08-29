"""持久化协调与尽力而为的补偿处理。"""


class IngestionPersistence:
    def __init__(self, vectors, metadata):
        self.vectors = vectors
        self.metadata = metadata

    def persist(self, rows, digest, document_id, source, chunk_count):
        inserted = False
        try:
            inserted = True
            if not self.vectors.insert(rows):
                raise RuntimeError("向量库写入失败")
            self.metadata.record(digest, document_id, source, chunk_count)
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
