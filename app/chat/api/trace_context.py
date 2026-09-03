"""统一解析当前请求的 trace_id，保证与日志链路一致。

中间件（main.py）在进入路由前会把 trace_id 写入 ``structlog.contextvars``，
日志与 Elasticsearch 都以该值为准。这里优先读取该值，避免直接读请求头
``X-Trace-Id`` 在客户端未携带时得到空串，导致审计记录与日志的 trace_id
对不上。缺失时依次回退到请求头、新生成一个 uuid4。
"""
from uuid import uuid4

import structlog
from fastapi import Request


def resolve_trace_id(request: Request) -> str:
    """返回当前请求的 trace_id：contextvars > 请求头 > 新生成。"""
    ctx = structlog.contextvars.get_contextvars()
    trace_id = ctx.get("trace_id")
    if isinstance(trace_id, str) and trace_id:
        return trace_id
    return request.headers.get("X-Trace-Id") or str(uuid4())
