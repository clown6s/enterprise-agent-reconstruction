"""Elasticsearch 集中日志适配器。

日志发送失败只回退到本地 logger，不影响业务请求；文档索引与日志索引完全分离。
索引按日滚动：`enterprise-agent-logs-YYYY.MM.DD`，与 Grafana 数据源匹配。
"""
from datetime import datetime, timezone
import logging

from app.chat.security.redaction import redact

logger = logging.getLogger(__name__)


class ElasticsearchLogSink:
    """把已脱敏的结构化日志写入按日滚动的独立 ES index。"""

    def __init__(self, *, host: str, index_prefix: str = "enterprise-agent-logs",
                 username: str = "", password: str = "", cert_fingerprint: str = "",
                 timeout: float = 2.0, client=None):
        if not host or not index_prefix:
            raise ValueError("日志 ES host 和 index_prefix 不能为空")
        if client is not None:
            self._client = client
            self._owns_client = False
        else:
            from elasticsearch import Elasticsearch
            kwargs = {"basic_auth": (username, password), "request_timeout": timeout}
            if cert_fingerprint:
                kwargs["ssl_assert_fingerprint"] = cert_fingerprint
            self._client = Elasticsearch(host, **kwargs)
            self._owns_client = True
        self._index_prefix = index_prefix

    def _index_name(self) -> str:
        return f"{self._index_prefix}-{datetime.now(timezone.utc).strftime('%Y.%m.%d')}"

    def emit(self, event: dict) -> bool:
        safe = {
            "@timestamp": datetime.now(timezone.utc).isoformat(),
            "service": "enterprise-agent",
        }
        for key, value in event.items():
            if key in {"password", "token", "authorization", "api_key", "prompt", "answer", "question"}:
                continue
            safe[key] = redact(value, max_length=2000) if isinstance(value, str) else value
        try:
            self._client.index(index=self._index_name(), document=safe)
            return True
        except Exception as exc:
            logger.warning("es_log_sink_failed: %s", type(exc).__name__)
            return False

    def close(self) -> None:
        if self._owns_client:
            self._client.close()
