"""接口层全局异常处理器：把业务异常翻译成 HTTP 响应。

设计约定（与业务层完全解耦）：
- 业务层/适配器层只负责抛出 :class:`AppError` 子类，绝不接触 HTTP。
- 本模块是唯一把「异常 → HTTP 状态码 + 响应体」的地方，且只做翻译，不写业务逻辑。
- FastAPI 应用通过 ``register_exception_handlers(app)`` 一次性挂载。
"""
from __future__ import annotations

import structlog
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from ..domain.exceptions import AppError, InfrastructureError, ValidationError


logger = structlog.get_logger(__name__)


def _response(status_code: int, error: str, error_type: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": error, "type": error_type},
    )


async def _handle_app_error(request: Request, exc: Exception) -> JSONResponse:
    """把业务异常映射成 HTTP 状态码与统一响应结构。"""
    if not isinstance(exc, AppError):
        # 处理器协议允许接收任意异常，注册到 AppError 时应只会收到业务异常。
        return await _handle_unexpected(request, exc)
    if isinstance(exc, ValidationError):
        return _response(400, str(exc), type(exc).__name__)
    if isinstance(exc, InfrastructureError):
        # 基础设施故障，客户端无需看到内部细节。
        return _response(503, "服务暂时不可用，请稍后重试", type(exc).__name__)
    # 其他业务异常（如 ProcessingError）视为服务端处理失败。
    logger.warning("business_error_handled", error=type(exc).__name__, detail=str(exc))
    return _response(500, str(exc), type(exc).__name__)


async def _handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
    """兜底：未知异常，完整堆栈只在这里记录一次。"""
    logger.exception("unhandled_error")
    return JSONResponse(
        status_code=500,
        content={"error": "Internal Server Error", "type": type(exc).__name__},
    )


def register_exception_handlers(app: FastAPI) -> None:
    """为 FastAPI 应用挂载统一的全局异常处理器。"""
    app.add_exception_handler(AppError, _handle_app_error)
    app.add_exception_handler(Exception, _handle_unexpected)
