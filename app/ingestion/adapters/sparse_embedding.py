"""确定性的稀疏词项向量适配器。"""
import hashlib
import re
from collections.abc import Sequence


class LocalSparseEmbedder:
    """将文本转换为 Milvus 可接受的稀疏向量，不依赖外部服务。"""

    def embed_batch(self, texts: Sequence[str]) -> list[dict[int, float]]:
        return [self._embed(text) for text in texts]

    @staticmethod
    def _embed(text: str) -> dict[int, float]:
        tokens = re.findall(r"[一-鿿]|[A-Za-z0-9_]+", text.lower())
        counts: dict[int, int] = {}
        for token in tokens:
            term_id = int.from_bytes(hashlib.sha256(token.encode("utf-8")).digest()[:4], "big")
            # Milvus 稀疏向量索引必须大于 0 且小于 2^32。
            term_id = max(1, term_id)
            counts[term_id] = counts.get(term_id, 0) + 1
        if not counts:
            # 空文本也需要可写入 Milvus 的稀疏项，避免空向量被服务端拒绝。
            fallback = int.from_bytes(hashlib.sha256(b"__empty__").digest()[:4], "big") or 1
            counts[fallback] = 1
        scale = max(counts.values())
        return {term_id: count / scale for term_id, count in counts.items()}
