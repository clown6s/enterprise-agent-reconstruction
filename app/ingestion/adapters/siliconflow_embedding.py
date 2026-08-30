"""SiliconFlow 向量 Embedding 适配器（实现 Embedder 端口）。"""
from collections.abc import Sequence

import math
import numbers
import time

import httpx
import structlog

from ..application.ports import Embedder


logger = structlog.get_logger(__name__)


class SiliconFlowError(RuntimeError):
    """通过 SiliconFlow 进行文本向量化失败时抛出的异常。"""


class SiliconFlowEmbedder:
    """基于 SiliconFlow（OpenAI 兼容接口）的批量文本向量化适配器。

    本适配器只负责把一串字符串转换成嵌入向量，不关心文档、切分器、
    Milvus 或摄入流程。它自身从不读取 API Key；凭据与端点由装配层注入。
    """

    def __init__(self, api_key: str, *, base_url: str, model: str,
                 embedding_dim: int, timeout: float = 60.0,
                 max_retries: int = 3, http_client: httpx.Client | None = None):
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._dim = int(embedding_dim)
        self._timeout = timeout
        self._max_retries = max(0, int(max_retries))
        self._client = http_client or httpx.Client(timeout=timeout)
        self._owns_client = http_client is None

    def embed_batch(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        texts = list(texts)
        if len(texts) > 32:
            result = []
            total_batches = (len(texts) + 31) // 32
            logger.info("embedding_batches_start", total_texts=len(texts),
                        batch_size=32, total_batches=total_batches)
            for batch_index, start in enumerate(range(0, len(texts), 32), 1):
                result.extend(self._embed_single_batch(
                    texts[start:start + 32], batch_index, total_batches))
            logger.info("embedding_batches_done", total_texts=len(texts),
                        total_batches=total_batches)
            return result
        return self._embed_single_batch(texts, 1, 1)

    def _embed_single_batch(self, texts: list[str], batch_index: int,
                            total_batches: int) -> list[list[float]]:
        started = time.perf_counter()
        logger.info("embedding_batch_start", batch=batch_index,
                    total_batches=total_batches, size=len(texts))
        body = {
            "model": self._model,
            "input": [text or "" for text in texts],
            "encoding_format": "float",
        }
        response = None
        for attempt in range(self._max_retries + 1):
            try:
                response = self._client.post(
                    f"{self._base_url}/embeddings",
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    json=body,
                    timeout=self._timeout,
                )
            except httpx.HTTPError as exc:
                if attempt >= self._max_retries:
                    raise SiliconFlowError(f"请求 SiliconFlow 失败: {type(exc).__name__}") from exc
                time.sleep(min(2 ** attempt, 8))
                continue
            if 200 <= response.status_code < 300:
                break
            if response.status_code not in (408, 429) and response.status_code < 500:
                break
            if attempt < self._max_retries:
                retry_after = response.headers.get("retry-after", "")
                try:
                    delay = min(float(retry_after), 30.0) if retry_after else min(2 ** attempt, 8)
                except ValueError:
                    delay = min(2 ** attempt, 8)
                time.sleep(delay)
        if response is None:
            raise SiliconFlowError("SiliconFlow 未返回响应")
        if not 200 <= response.status_code < 300:
            raise SiliconFlowError(
                f"SiliconFlow 返回错误状态 {response.status_code}: {response.text[:200]}")
        try:
            data = response.json()
            items = data["data"]
            if not isinstance(items, list):
                raise TypeError("data 不是列表")
        except (ValueError, KeyError, TypeError) as exc:
            raise SiliconFlowError("SiliconFlow 响应结构无效") from exc

        # 服务端可能乱序返回向量，按 index 恢复顺序。
        ordered = [None] * len(texts)
        seen_indexes = set()
        for item in items:
            if not isinstance(item, dict):
                raise SiliconFlowError("SiliconFlow 返回了无效数据项")
            index = item.get("index")
            vector = item.get("embedding")
            if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < len(ordered):
                raise SiliconFlowError("SiliconFlow 返回了无效 index")
            if index in seen_indexes:
                raise SiliconFlowError(f"SiliconFlow 返回了重复 index: {index}")
            seen_indexes.add(index)
            if not isinstance(vector, list):
                raise SiliconFlowError(f"SiliconFlow 返回了无效向量(index={index})")
            if not all(isinstance(value, numbers.Real) and math.isfinite(value) for value in vector):
                raise SiliconFlowError(f"SiliconFlow 向量包含无效数值(index={index})")
            ordered[index] = vector
        if any(vector is None for vector in ordered):
            raise SiliconFlowError("SiliconFlow 返回向量数量与请求不一致")
        for vector in ordered:
            if len(vector) != self._dim:
                raise SiliconFlowError(
                    f"SiliconFlow 返回向量维度 {len(vector)}，期望 {self._dim}")
        vectors = [list(vector) for vector in ordered]
        logger.info("embedding_batch_done", batch=batch_index,
                    total_batches=total_batches, size=len(texts),
                    elapsed_seconds=round(time.perf_counter() - started, 3),
                    dimensions=self._dim)
        return vectors

    def close(self) -> None:
        if self._owns_client:
            self._client.close()
