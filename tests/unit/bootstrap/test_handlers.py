"""全局异常处理器的单元测试：校验统一错误响应结构与 trace_id。"""
from uuid import uuid4

import structlog
from fastapi import Body, FastAPI, Request
from fastapi.testclient import TestClient

from app.ingestion.bootstrap.handlers import register_exception_handlers
from app.ingestion.domain.exceptions import (
    InfrastructureError,
    ProcessingError,
    ValidationError,
)


def _build_app() -> FastAPI:
    """构造一个仅挂载异常处理器的临时应用，便于聚焦错误响应行为。"""
    app = FastAPI()
    register_exception_handlers(app)

    @app.middleware("http")
    async def bind_trace_id(request: Request, call_next):
        # 复刻 main.py：请求头优先，缺失则生成，绑定到 contextvars，响应头回传。
        trace_id = request.headers.get("X-Trace-Id") or str(uuid4())
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(trace_id=trace_id)
        try:
            response = await call_next(request)
        except Exception:
            raise
        response.headers["X-Trace-Id"] = trace_id
        return response


    @app.get("/validation")
    def raise_validation():
        raise ValidationError("参数不合法")

    @app.get("/infra")
    def raise_infra():
        raise InfrastructureError("依赖不可用")

    @app.get("/processing")
    def raise_processing():
        raise ProcessingError("处理失败")

    @app.get("/http-str")
    def raise_http_str():
        from fastapi import HTTPException
        raise HTTPException(status_code=429, detail="请求过于频繁，请稍后重试")

    @app.get("/http-dict")
    def raise_http_dict():
        from fastapi import HTTPException
        raise HTTPException(status_code=503, detail={"status": "unavailable"})

    @app.get("/boom")
    def raise_unexpected():
        raise RuntimeError("内部出错")

    @app.post("/echo")
    def echo(name: str = Body(..., min_length=5)):
        return {"name": name}

    return app


def _get(url: str, trace_id: str = "test-trace-123"):
    """带固定 X-Trace-Id 发起 GET，方便断言链路一致性。"""
    return TestClient(_build_app()).get(url, headers={"X-Trace-Id": trace_id})


def test_validation_error_shape():
    """ValidationError 返回 400 与统一结构。"""
    response = _get("/validation")
    assert response.status_code == 400
    body = response.json()
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert body["error"]["message"] == "参数不合法"
    assert body["error"]["details"] == []
    assert body["trace_id"] == "test-trace-123"
    # 响应头也应带同一个 trace_id。
    assert response.headers["X-Trace-Id"] == "test-trace-123"


def test_infrastructure_error_does_not_leak_details():
    """InfrastructureError 返回 503 且隐藏内部细节。"""
    response = _get("/infra")
    assert response.status_code == 503
    body = response.json()
    assert body["error"]["code"] == "INFRASTRUCTURE_ERROR"
    assert body["error"]["message"] == "服务暂时不可用，请稍后重试"


def test_business_error_defaults_to_500():
    """其他业务异常（如 ProcessingError）返回 500 与 BUSINESS_ERROR。"""
    response = _get("/processing")
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "BUSINESS_ERROR"


def test_http_exception_string_detail():
    """HTTPException 字符串 detail 作为 message，details 为空。"""
    response = _get("/http-str")
    assert response.status_code == 429
    body = response.json()
    assert body["error"]["code"] == "RATE_LIMITED"
    assert body["error"]["message"] == "请求过于频繁，请稍后重试"
    assert body["error"]["details"] == []


def test_http_exception_dict_detail_goes_to_details():
    """HTTPException 字典 detail（如 /readyz 的 payload）放入 details。"""
    response = _get("/http-dict")
    assert response.status_code == 503
    body = response.json()
    assert body["error"]["code"] == "SERVICE_UNAVAILABLE"
    assert body["error"]["message"] == "服务暂时不可用"
    assert body["error"]["details"] == {"status": "unavailable"}


def test_unexpected_error_is_opaqued_but_traced():
    """未知异常返回 500 与统一 code，且不泄露内部堆栈细节。"""
    response = TestClient(
        _build_app(), raise_server_exceptions=False,
    ).get("/boom", headers={"X-Trace-Id": "test-trace-123"})
    assert response.status_code == 500
    body = response.json()
    assert body["error"]["code"] == "INTERNAL_ERROR"
    assert body["error"]["message"] == "Internal Server Error"
    assert "RuntimeError" not in body["error"]["message"]
    assert body["trace_id"] == "test-trace-123"


def test_trace_id_generated_when_header_missing():
    """无 X-Trace-Id 时也应生成并回传一个 trace_id。"""
    response = TestClient(_build_app()).get("/validation")
    assert response.status_code == 400
    body = response.json()
    assert body["trace_id"]

def test_request_validation_error_shape():
    """FastAPI 422 参数校验错误被统一成 VALIDATION_ERROR。"""
    app = _build_app()

    @app.post("/echo")
    def echo(name: str = Body(..., min_length=5)):
        return {"name": name}

    response = TestClient(app).post(
        "/echo", json={"name": "x"}, headers={"X-Trace-Id": "t-1"})
    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert body["error"]["message"] == "请求参数校验失败"
    assert isinstance(body["error"]["details"], list)
    assert body["trace_id"] == "t-1"