"""飞书 HTTP 客户端：Token 缓存、消息回复和有限重试。"""
import time
import threading

import httpx


class FeishuApiClient:
    def __init__(self, *, app_id: str, app_secret: str,
                 base_url: str = "https://open.feishu.cn",
                 timeout: float = 10.0, max_retries: int = 3,
                 http_client: httpx.Client | None = None):
        self._app_id = app_id
        self._app_secret = app_secret
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._max_retries = max(0, int(max_retries))
        self._client = http_client or httpx.Client(timeout=timeout)
        self._owns_client = http_client is None
        self._token = None
        self._token_expires_at = 0.0
        self._lock = threading.Lock()

    def app_access_token(self) -> str:
        now = time.time()
        with self._lock:
            if self._token and now < self._token_expires_at - 60:
                return self._token
            response = self._request(
                "POST", "/open-apis/auth/v3/app_access_token/internal",
                json={"app_id": self._app_id, "app_secret": self._app_secret},
                auth=False,
            )
            data = response.json()
            token = data.get("app_access_token")
            if not token:
                raise RuntimeError("飞书 Token 响应无效")
            self._token = token
            self._token_expires_at = now + int(data.get("expire", 7200))
            return token

    def reply_text(self, message_id: str, text: str) -> bool:
        content = text[:6000]
        response = self._request(
            "POST", f"/open-apis/im/v1/messages/{message_id}/reply",
            params={"receive_id_type": "chat_id"},
            json={"msg_type": "text", "content": self._json_text(content)},
        )
        return response.status_code == 200

    def reply_card(self, message_id: str, card_json: str) -> bool:
        response = self._request(
            "POST", f"/open-apis/im/v1/messages/{message_id}/reply",
            params={"receive_id_type": "chat_id"},
            json={"msg_type": "interactive", "content": card_json},
        )
        return response.status_code == 200

    def send_text(self, open_id: str, text: str) -> bool:
        response = self._request(
            "POST", "/open-apis/im/v1/messages",
            params={"receive_id_type": "open_id"},
            json={"receive_id": open_id, "msg_type": "text",
                  "content": self._json_text(text[:6000])},
        )
        return response.status_code == 200

    @staticmethod
    def _json_text(text: str) -> str:
        import json
        return json.dumps({"text": text}, ensure_ascii=False)

    def _request(self, method: str, path: str, *, auth: bool = True, **kwargs):
        headers = dict(kwargs.pop("headers", {}) or {})
        if auth:
            headers["Authorization"] = f"Bearer {self.app_access_token()}"
        for attempt in range(self._max_retries + 1):
            try:
                response = self._client.request(method, self._base_url + path,
                                                headers=headers, timeout=self._timeout,
                                                **kwargs)
            except httpx.HTTPError:
                if attempt >= self._max_retries:
                    raise
                time.sleep(min(2 ** attempt, 8))
                continue
            if response.status_code < 500 and response.status_code not in (408, 429):
                return response
            if attempt < self._max_retries:
                time.sleep(min(2 ** attempt, 8))
        return response

    def close(self) -> None:
        if self._owns_client:
            self._client.close()
