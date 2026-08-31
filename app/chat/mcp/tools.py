"""MCP tool handlers; transport concerns stay outside chat application."""
from dataclasses import asdict

from ..application.chat_service import ChatService
from ..application.context_builder import ContextBuilder
from ..application.rag_answerer import RagAnswerer
from ..application.sop.sop_service import SopService
from ..application.nl2sql.nl2sql_service import Nl2SqlService
from ..domain.models import ChatStatus, Intent
from ..mcp.bridge import run_sync


_MAX_TOP_K = 20


def _identity(tenant_id: str, user_id: str) -> tuple[str, str]:
    if not isinstance(tenant_id, str) or not tenant_id.strip():
        raise ValueError("tenant_id 不能为空")
    if not isinstance(user_id, str) or not user_id.strip():
        raise ValueError("user_id 不能为空")
    return tenant_id.strip(), user_id.strip()


def _result_dict(result) -> dict:
    payload = asdict(result)
    payload["status"] = result.status.value
    payload["mode"] = result.mode.value
    payload["citations"] = [asdict(item) for item in result.citations]
    return payload


class ChatTools:
    """Application-facing tool facade with identity and input validation."""

    def __init__(self, service: ChatService):
        self.service = service

    async def chat_ask(self, question: str, conversation_id: str,
                       tenant_id: str, user_id: str, confirmed: bool = False) -> dict:
        _identity(tenant_id, user_id)
        if not isinstance(question, str) or not question.strip():
            raise ValueError("question 不能为空")
        return _result_dict(await run_sync(
            self.service.ask, question.strip(), conversation_id=conversation_id,
            confirmed=confirmed,
        ))

    async def document_search(self, query: str, top_k: int,
                              tenant_id: str, user_id: str) -> dict:
        _identity(tenant_id, user_id)
        if not isinstance(query, str) or not query.strip():
            raise ValueError("query 不能为空")
        if isinstance(top_k, bool) or not isinstance(top_k, int) or not 1 <= top_k <= _MAX_TOP_K:
            raise ValueError(f"top_k 必须在 1 到 {_MAX_TOP_K} 之间")
        answerer = self.service.rag
        items = await run_sync(answerer.retriever.retrieve, query.strip(), top_k=top_k)
        _, citations = answerer.context_builder.build(items)
        return {"items": [asdict(item) for item in items],
                "citations": [asdict(item) for item in citations]}

    async def sop_get_step(self, query: str, conversation_id: str,
                           tenant_id: str, user_id: str,
                           confirmed: bool = False) -> dict:
        _identity(tenant_id, user_id)
        if not isinstance(query, str) or not query.strip():
            raise ValueError("query 不能为空")
        result = await run_sync(
            self.service.sop.handle, query.strip(), conversation_id, [],
            confirmed=confirmed,
        )
        return _result_dict(result)

    async def readonly_sql_query(self, question: str, tenant_id: str,
                                 user_id: str) -> dict:
        _identity(tenant_id, user_id)
        if not isinstance(question, str) or not question.strip():
            raise ValueError("question 不能为空")
        result = await run_sync(self.service.nl2sql.answer,
                                question.strip(), f"mcp:{tenant_id}:{user_id}")
        return _result_dict(result)
