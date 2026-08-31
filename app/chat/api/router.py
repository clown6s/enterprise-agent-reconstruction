"""HTTP adapter for the chat application."""
from dataclasses import asdict
from typing import Callable

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ..application.chat_service import ChatService
from ..domain.models import ChatResult


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


def create_router(service_provider: Callable[[], ChatService]) -> APIRouter:
    router = APIRouter(prefix="/chat", tags=["chat"])

    def service() -> ChatService:
        return service_provider()

    @router.post("")
    def chat(request: ChatRequest, chat: ChatService = Depends(service)):
        return _serialize(chat.ask(
            request.question, conversation_id=request.conversation_id,
            confirmed=request.confirmed,
        ))

    return router
