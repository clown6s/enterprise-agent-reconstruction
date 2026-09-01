"""OpenTelemetry 初始化与 span 辅助函数。

监控 SDK 只允许出现在基础设施层；导出失败不能阻断业务请求。
"""
import os
from contextlib import contextmanager

from opentelemetry import trace
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor


_provider: TracerProvider | None = None


def setup_tracing() -> TracerProvider:
    """初始化全局 tracer provider；无 OTLP 地址时仍启用本地 span。"""
    global _provider
    if _provider is not None:
        return _provider
    provider = TracerProvider(resource=Resource.create({
        SERVICE_NAME: os.getenv("OTEL_SERVICE_NAME", "enterprise-agent"),
    }))
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip()
    if endpoint:
        try:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
            provider.add_span_processor(BatchSpanProcessor(
                OTLPSpanExporter(endpoint=endpoint, timeout=5)))
        except Exception:
            # 配置/导出器不可用时保留本地 provider，不能阻断应用启动。
            pass
    trace.set_tracer_provider(provider)
    _provider = provider
    return provider


def shutdown_tracing() -> None:
    global _provider
    if _provider is not None:
        try:
            _provider.shutdown()
        finally:
            _provider = None


def tracer(name: str = "enterprise-agent"):
    return trace.get_tracer(name)


@contextmanager
def span(name: str, **attributes):
    """创建一个只写低敏属性的 span。"""
    with tracer().start_as_current_span(name) as current:
        for key, value in attributes.items():
            if value is not None:
                current.set_attribute(key, value)
        yield current
