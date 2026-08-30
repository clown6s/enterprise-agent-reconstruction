"""日志装配。与业务代码解耦：仅负责把 structlog 配置好。

设计约定：
- 本模块不 import 任何业务模块，业务模块也不 import 本模块。
- 只在「进程入口」调用一次 ``setup_logging()``（应用启动、脚本 main）。
- 业务代码统一通过 ``structlog.get_logger(__name__)`` 取 logger，避免重复配置。
- 配置由环境变量驱动，默认开发可读输出，生产输出 JSON。
"""
from __future__ import annotations

import logging
import os

import structlog


def _renderer():
    """按环境选择渲染器：生产 JSON（便于采集），开发 Console（可读）。"""
    env = os.getenv("ENV", "dev").lower()
    if env in {"prod", "production"}:
        return structlog.processors.JSONRenderer()
    return structlog.dev.ConsoleRenderer()


def _level() -> int:
    return logging.getLevelName(os.getenv("LOG_LEVEL", "INFO"))


def setup_logging() -> None:
    """配置全局 structlog，幂等，可安全重复调用。"""
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,   # 请求级上下文（trace_id 等）
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,      # 异常堆栈
            structlog.processors.UnicodeDecoder(),
            _renderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(_level()),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
