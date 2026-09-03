"""聊天应用的 HTTP 适配器。"""
from dataclasses import asdict
import time
from typing import Callable

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from ..application.chat_service import ChatService
from ..application.context import RequestContext
from ..domain.models import ChatResult
from .trace_context import resolve_trace_id


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=12000)
    conversation_id: str = Field(default="default", min_length=1, max_length=128)
    confirmed: bool = False


def _serialize(result: ChatResult) -> dict:
    payload = asdict(result)
    payload["status"] = result.status.value
    payload["mode"] = result.mode.value
    payload["citations"] = [asdict(item) for item in result.citations]
    return payload


def _anonymous_principal(_request: Request):
    return None


def create_router(service_provider: Callable[[], ChatService],
                  principal_provider: Callable[[Request], object] | None = None,
                  rate_limiter=None, usage_meter=None) -> APIRouter:
    router = APIRouter(prefix="/chat", tags=["chat"])
    principal_dependency = principal_provider or _anonymous_principal

    def service() -> ChatService:
        return service_provider()

    @router.post("")
    def chat(http_request: Request, request: ChatRequest,
             chat: ChatService = Depends(service),
             principal=Depends(principal_dependency)):
        if rate_limiter is not None:
            key = (f"{principal.tenant_id}:{principal.user_id}"
                   if principal is not None else http_request.client.host)
            if not rate_limiter.allow(key):
                from fastapi import HTTPException
                raise HTTPException(status_code=429, detail="请求过于频繁，请稍后重试")
        # 优先取中间件绑定的 trace_id，保证审计记录与日志/ES 链路一致。
        trace_id = resolve_trace_id(http_request)
        if principal is None:
            # 向后兼容的直接测试/伪造对象构造。
            context = RequestContext(trace_id=trace_id)
        else:
            context = RequestContext(
                trace_id=trace_id,
                tenant_id=principal.tenant_id, user_id=principal.user_id,
                roles=principal.roles, permissions=principal.permissions,
                authenticated=True,
                expires_at=(principal.expires_at.isoformat()
                            if principal.expires_at else None),
                department_ids=principal.department_ids,
            )
        started = time.perf_counter()
        result = chat.ask(
            request.question, conversation_id=request.conversation_id,
            confirmed=request.confirmed, context=context,
        )
        if usage_meter is not None:
            try:
                usage_meter.record(
                    f"{context.tenant_id}:{context.user_id}",
                    input_chars=len(request.question), output_chars=len(result.answer),
                    duration_ms=int((time.perf_counter() - started) * 1000),
                )
            except Exception:
                # 指标绝不能把成功回答变成失败。
                pass
        return _serialize(result)

    return router
