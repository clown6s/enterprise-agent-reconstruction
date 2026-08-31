"""SiliconFlow 重排序适配器（实现 Reranker 端口）。"""
from collections.abc import Sequence

import math
import numbers
import time

import httpx


class SiliconFlowRerankError(RuntimeError):
    """通过 SiliconFlow 进行重排序失败时抛出的异常。"""


class SiliconFlowReranker:
    """基于 SiliconFlow rerank 接口的 cross-encoder 重排序。

    只负责给一组候选文本按与 query 的相关性打分排序，不关心检索
    策略、向量库或摄入流程。它自身从不读取 API Key；凭据与端点由
    装配层注入。
    """

    def __init__(self, api_key: str, *, base_url: str, model: str,
                 timeout: float = 60.0, max_retries: int = 3,
                 http_client: httpx.Client | None = None):
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout = timeout
        self._max_retries = max(0, int(max_retries))
        self._client = http_client or httpx.Client(timeout=timeout)
        self._owns_client = http_client is None

    def rerank(self, query: str, texts: Sequence[str], *,
               top_n: int) -> list[tuple[int, float]]:
        if not isinstance(query, str) or not query.strip():
            raise ValueError("query 必须是非空字符串")
        texts = list(texts)
        if not texts:
            return []
        if (isinstance(top_n, bool) or not isinstance(top_n, int)
                or not 1 <= top_n <= len(texts)):
            raise ValueError("top_n 必须是 1 到候选数之间的整数")
        body = {
            "model": self._model,
            "query": query,
            "documents": [text or "" for text in texts],
            "top_n": top_n,
            "return_documents": False,
        }
        response = None
        for attempt in range(self._max_retries + 1):
            try:
                response = self._client.post(
                    f"{self._base_url}/rerank",
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    json=body,
                    timeout=self._timeout,
                )
            except httpx.HTTPError as exc:
                if attempt >= self._max_retries:
                    raise SiliconFlowRerankError(
                        f"请求 SiliconFlow 重排序失败: {type(exc).__name__}") from exc
                time.sleep(min(2 ** attempt, 8))
                continue
            if 200 <= response.status_code < 300:
                break
            if response.status_code not in (408, 429) and response.status_code < 500:
                break
            if attempt < self._max_retries:
                retry_after = response.headers.get("retry-after", "")
                delay = min(2 ** attempt, 8)
                if retry_after:
                    try:
                        parsed = float(retry_after)
                        if math.isfinite(parsed) and parsed >= 0:
                            delay = min(parsed, 30.0)
                    except ValueError:
                        delay = min(2 ** attempt, 8)
                time.sleep(delay)
        if response is None:
            raise SiliconFlowRerankError("SiliconFlow 重排序未返回响应")
        if not 200 <= response.status_code < 300:
            raise SiliconFlowRerankError(
                f"SiliconFlow 重排序返回错误状态 {response.status_code}: {response.text[:200]}")
        try:
            data = response.json()
            results = data["results"]
            if not isinstance(results, list):
                raise TypeError("results 不是列表")
        except (ValueError, KeyError, TypeError) as exc:
            raise SiliconFlowRerankError("SiliconFlow 重排序响应结构无效") from exc

        ranked = []
        seen_indexes = set()
        for item in results:
            if not isinstance(item, dict):
                raise SiliconFlowRerankError("SiliconFlow 重排序返回了无效数据项")
            index = item.get("index")
            score = item.get("relevance_score")
            if (isinstance(index, bool) or not isinstance(index, int)
                    or not 0 <= index < len(texts)):
                raise SiliconFlowRerankError("SiliconFlow 重排序返回了无效 index")
            if index in seen_indexes:
                raise SiliconFlowRerankError(f"SiliconFlow 重排序返回了重复 index: {index}")
            seen_indexes.add(index)
            if (not isinstance(score, numbers.Real) or isinstance(score, bool)
                    or not math.isfinite(score)):
                raise SiliconFlowRerankError(f"SiliconFlow 重排序分数无效(index={index})")
            ranked.append((index, float(score)))
        if len(ranked) != top_n:
            raise SiliconFlowRerankError("SiliconFlow 重排序返回数量与请求不一致")
        return sorted(ranked, key=lambda pair: pair[1], reverse=True)

    def close(self) -> None:
        if self._owns_client:
            self._client.close()
