"""SiliconFlow 向量 Embedding 适配器（实现 Embedder 端口）。"""
from collections.abc import Sequence

import math
import numbers

import httpx

from ..application.ports import Embedder


class SiliconFlowError(RuntimeError):
    """通过 SiliconFlow 进行文本向量化失败时抛出的异常。"""


class SiliconFlowEmbedder:
    """基于 SiliconFlow（OpenAI 兼容接口）的批量文本向量化适配器。

    本适配器只负责把一串字符串转换成嵌入向量，不关心文档、切分器、
    Milvus 或摄入流程。它自身从不读取 API Key；凭据与端点由装配层注入。
    """

    def __init__(self, api_key: str, *, base_url: str, model: str,
                 embedding_dim: int, timeout: float = 60.0):
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._dim = int(embedding_dim)
        self._timeout = timeout

    def embed_batch(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        texts = list(texts)
        if len(texts) > 32:
            result = []
            for start in range(0, len(texts), 32):
                result.extend(self.embed_batch(texts[start:start + 32]))
            return result
        body = {
            "model": self._model,
            "input": [text or "" for text in texts],
            "encoding_format": "float",
        }
        try:
            response = httpx.post(
                f"{self._base_url}/embeddings",
                headers={"Authorization": f"Bearer {self._api_key}"},
                json=body,
                timeout=self._timeout,
            )
        except httpx.HTTPError as exc:
            raise SiliconFlowError(f"请求 SiliconFlow 失败: {type(exc).__name__}") from exc
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
        return [list(vector) for vector in ordered]
