"""日志装配。与业务代码解耦：仅负责把 structlog 配置好。

设计约定：
- 本模块不 import 任何业务模块，业务模块也不 import 本模块。
- 只在「进程入口」调用一次 ``setup_logging()``（应用启动、脚本 main）。
- 业务代码统一通过 ``structlog.get_logger(__name__)`` 取 logger。
- 配置由环境变量驱动，默认开发可读输出，生产输出 JSON。
- 可注入日志 sink（如 ElasticsearchLogSink）转发脱敏事件；sink 失败不阻断业务。
"""
from __future__ import annotations

import logging
import os
from typing import Any

import structlog

# 进程级 sink 持有：setup_logging 注入后可在 shutdown 时关闭
_SINK: Any = None


def _renderer():
    """按环境选择渲染器：生产 JSON（便于采集），开发 Console（可读）。"""
    env = os.getenv("ENV", "dev").lower()
    if env in {"prod", "production"}:
        return structlog.processors.JSONRenderer()
    return structlog.dev.ConsoleRenderer()


def _level() -> int:
    name = (os.getenv("LOG_LEVEL", "INFO") or "INFO").upper()
    level = logging.getLevelNamesMapping().get(name)
    # 未识别的级别名回退到 INFO，避免 getLevelName 返回字符串造成类型歧义。
    return level if level is not None else logging.INFO


def _forward_to_sink(_logger, _method, event_dict):
    """把脱敏后的结构化事件转发到 sink；失败只降级，不阻断业务。"""
    if _SINK is not None:
        try:
            _SINK.emit(dict(event_dict))
        except Exception:
            # sink 内部已自行捕获；这里做最后兜底，绝不让日志拖垮业务。
            pass
    return event_dict


def setup_logging(es_sink=None) -> None:
    """配置全局 structlog，可注入日志 sink；幂等可重复调用。"""
    global _SINK
    if es_sink is not None:
        _SINK = es_sink
    processors = [
        structlog.contextvars.merge_contextvars,   # 请求级上下文（trace_id 等）
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,      # 异常堆栈
        structlog.processors.UnicodeDecoder(),
        _forward_to_sink,                          # 在渲染前把脱敏事件交给 sink
        _renderer(),
    ]
    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(_level()),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=False,          # 允许后续 attach sink 后生效
    )


def close_log_sink() -> None:
    """关闭进程级日志 sink（在应用 shutdown 时调用）。"""
    global _SINK
    if _SINK is not None:
        try:
            _SINK.close()
        finally:
            _SINK = None
