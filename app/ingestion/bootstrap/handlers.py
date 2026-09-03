"""接口层全局异常处理器：把业务异常翻译成统一格式的 HTTP 响应。

设计约定（与业务层完全解耦）：
- 业务层/适配器层只负责抛出 :class:`AppError` 子类，绝不接触 HTTP。
- 本模块是唯一把「异常 → HTTP 状态码 + 响应体」的地方，且只做翻译，不写业务逻辑。
- 所有错误响应统一为 ``{"error": {"code", "message", "details"}, "trace_id"}``，
  方便客户端统一解析，也便于通过 trace_id 关联请求与日志链路。
- FastAPI 应用通过 ``register_exception_handlers(app)`` 一次性挂载。

注意：FastAPI 的异常处理器协议要求形参能接收任意 ``Exception``，因此各处理函数
形参用基类型并在内部用 ``isinstance`` 收窄，以满足类型检查。
"""
from __future__ import annotations

from typing import Any

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from ..domain.exceptions import AppError, InfrastructureError, ValidationError


logger = structlog.get_logger(__name__)

# HTTP 状态码 -> 稳定、机器可读的错误码。
_STATUS_CODES = {
    400: "BAD_REQUEST",
    401: "UNAUTHORIZED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    409: "CONFLICT",
    422: "VALIDATION_ERROR",
    429: "RATE_LIMITED",
    503: "SERVICE_UNAVAILABLE",
}

# HTTP 状态码 -> 兜底文案（当 detail 不是字符串时使用）。
_GENERIC_MESSAGES = {
    400: "请求参数错误",
    401: "未授权",
    403: "禁止访问",
    404: "资源不存在",
    409: "资源冲突",
    422: "请求参数校验失败",
    429: "请求过于频繁",
    500: "服务器内部错误",
    503: "服务暂时不可用",
}


def _request_trace_id(request: Request) -> str:
    """从请求级上下文取 trace_id，缺失时回退到请求头。"""
    ctx = structlog.contextvars.get_contextvars()
    trace_id = ctx.get("trace_id")
    if not isinstance(trace_id, str) or not trace_id:
        trace_id = request.headers.get("X-Trace-Id", "")
    return trace_id or ""


def _error_response(request: Request, status_code: int, code: str,
                    message: str, details: Any = None) -> JSONResponse:
    """构造统一的错误响应，携带 error 结构体与 trace_id，并补齐响应头。"""
    trace_id = _request_trace_id(request)
    content: dict[str, Any] = {
        "error": {"code": code, "message": message,
                  "details": details if details is not None else []},
    }
    if trace_id:
        content["trace_id"] = trace_id
    response = JSONResponse(status_code=status_code, content=content)
    if trace_id:
        # 异常由处理器承接时，中间件后续可能不会走到设置响应头的地方，这里主动补齐，
        # 保证客户端从响应头或响应体都能取到同一个 trace_id。
        response.headers["X-Trace-Id"] = trace_id
    return response


async def _handle_app_error(request: Request, exc: Exception) -> JSONResponse:
    """把业务异常映射成统一错误响应。"""
    if not isinstance(exc, AppError):
        # 协议形参宽松，但注册到 AppError 时应只会收到业务异常。
        return await _handle_unexpected(request, exc)
    logger.warning("business_error_handled", error=type(exc).__name__, detail=str(exc))
    if isinstance(exc, ValidationError):
        return _error_response(request, 400, "VALIDATION_ERROR", str(exc))
    if isinstance(exc, InfrastructureError):
        # 基础设施故障，客户端无需看到内部细节。
        return _error_response(request, 503, "INFRASTRUCTURE_ERROR",
                               "服务暂时不可用，请稍后重试")
    # 其他业务异常（如 ProcessingError）视为服务端处理失败。
    return _error_response(request, 500, "BUSINESS_ERROR", str(exc))


async def _handle_http_error(request: Request, exc: Exception) -> JSONResponse:
    """把 FastAPI 的 HTTPException 统一成标准错误结构。"""
    if not isinstance(exc, StarletteHTTPException):
        return await _handle_unexpected(request, exc)
    code = _STATUS_CODES.get(exc.status_code, "HTTP_ERROR")
    detail = exc.detail
    # 非字符串 detail（如 /readyz 的状态 payload）放入 details，message 用兜底文案。
    message = detail if isinstance(detail, str) else _GENERIC_MESSAGES.get(
        exc.status_code, "请求失败")
    details = [] if isinstance(detail, str) else detail
    return _error_response(request, exc.status_code, code, message, details)


async def _handle_validation_error(request: Request, exc: Exception) -> JSONResponse:
    """把 FastAPI 参数校验错误（422）统一成标准错误结构。"""
    if not isinstance(exc, RequestValidationError):
        return await _handle_unexpected(request, exc)
    return _error_response(request, 422, "VALIDATION_ERROR",
                           "请求参数校验失败", exc.errors())


async def _handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
    """兜底：未知异常，完整堆栈只在日志里记录一次，不泄露内部细节给客户端。"""
    logger.exception("unhandled_error", exc_type=type(exc).__name__)
    return _error_response(request, 500, "INTERNAL_ERROR", "Internal Server Error")


def register_exception_handlers(app: FastAPI) -> None:
    """为 FastAPI 应用挂载统一的全局异常处理器。

    按具体程度从最具体到最通用注册，FastAPI 会按异常类型取最匹配的处理器。
    """
    app.add_exception_handler(RequestValidationError, _handle_validation_error)
    app.add_exception_handler(StarletteHTTPException, _handle_http_error)
    app.add_exception_handler(AppError, _handle_app_error)
    app.add_exception_handler(Exception, _handle_unexpected)