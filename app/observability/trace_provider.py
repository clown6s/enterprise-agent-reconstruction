"""把 OpenTelemetry 实现适配为应用层 TraceProvider 端口。"""
from .tracing import span


class OtelTraceProvider:
    """实现 chat.application.ports.TraceProvider，不向业务暴露 OTel 类型。"""

    def span(self, name: str, **attributes):
        return span(name, **attributes)
