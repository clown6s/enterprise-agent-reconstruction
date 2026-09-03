"""OpenAI 兼容聊天适配器（适用于 SiliconFlow 或 DeepSeek）。"""
import time

import httpx

from ..application.ports import LLM
from ..domain.exceptions import LlmError
from ..domain.models import ChatMessage
from app.observability.tracing import span


class OpenAiCompatChat:
    """通过 OpenAI 兼容的 /chat/completions 端点完成聊天请求。

    这里只负责把消息映射为网络传输格式；凭据和端点由组合根注入，
    与 SiliconFlow 嵌入器及重排器适配器保持一致。
    """

    def __init__(self, api_key: str, *, base_url: str, model: str,
                 temperature: float = 0.2, max_tokens: int = 1024,
                 timeout: float = 90.0, max_retries: int = 2,
                 http_client: httpx.Client | None = None):
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._timeout = timeout
        self._max_retries = max(0, int(max_retries))
        self._client = http_client or httpx.Client(timeout=timeout)
        self._owns_client = http_client is None

    def chat(self, messages: list[ChatMessage]) -> str:
        payload = {
            "model": self._model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "temperature": self._temperature,
            "max_tokens": self._max_tokens,
        }
        with span("llm.chat", kind="completion", model=self._model,
                  status="attempt"):
            return self._chat_with_span(payload)

    def _chat_with_span(self, payload: dict) -> str:
        response = None
        for attempt in range(self._max_retries + 1):
            try:
                response = self._client.post(
                    f"{self._base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    json=payload,
                    timeout=self._timeout,
                )
            except httpx.HTTPError as exc:
                if attempt >= self._max_retries:
                    raise LlmError(f"请求 LLM 失败: {type(exc).__name__}") from exc
                time.sleep(min(2 ** attempt, 8))
                continue
            if 200 <= response.status_code < 300:
                break
            if response.status_code not in (408, 429) and response.status_code < 500:
                break
            if attempt < self._max_retries:
                time.sleep(min(2 ** attempt, 8))
        if response is None or not 200 <= response.status_code < 300:
            status = response.status_code if response is not None else "no-response"
            raise LlmError(f"LLM 返回错误状态 {status}: "
                           f"{(response.text[:200] if response is not None else '')}")
        try:
            data = response.json()
            content = data["choices"][0]["message"]["content"]
        except (ValueError, KeyError, TypeError, IndexError) as exc:
            raise LlmError("LLM 响应结构无效") from exc
        if not isinstance(content, str):
            raise LlmError("LLM 响应 content 非字符串")
        return content.strip()

    def close(self) -> None:
        if self._owns_client:
            self._client.close()
