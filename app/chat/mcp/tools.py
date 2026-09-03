"""MCP 工具处理器，传输层逻辑与聊天应用层保持分离。"""
from dataclasses import asdict

from ..application.chat_service import ChatService
from ..application.context import RequestContext
from ..application.context_builder import ContextBuilder
from ..application.rag_answerer import RagAnswerer
from ..application.sop.sop_service import SopService
from ..application.nl2sql.nl2sql_service import Nl2SqlService
from ..domain.models import ChatStatus, Intent
from ..mcp.bridge import run_sync


_MAX_TOP_K = 20


def _identity(context: RequestContext) -> RequestContext:
    if not isinstance(context, RequestContext) or not context.authenticated:
        raise PermissionError("MCP 请求未认证")
    if not context.tenant_id or not context.user_id:
        raise PermissionError("MCP 请求缺少可信身份")
    return context


def _result_dict(result) -> dict:
    payload = asdict(result)
    payload["status"] = result.status.value
    payload["mode"] = result.mode.value
    payload["citations"] = [asdict(item) for item in result.citations]
    return payload


class ChatTools:
    """面向应用的工具门面，负责身份与输入校验。"""

    def __init__(self, service: ChatService):
        self.service = service

    async def chat_ask(self, question: str, conversation_id: str,
                       confirmed: bool = False, *, context: RequestContext) -> dict:
        context = _identity(context)
        if not isinstance(question, str) or not question.strip():
            raise ValueError("question 不能为空")
        return _result_dict(await run_sync(
            self.service.ask, question.strip(), conversation_id=conversation_id,
            confirmed=confirmed, context=context,
        ))

    async def document_search(self, query: str, top_k: int,
                              *, context: RequestContext) -> dict:
        _identity(context)
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
                           confirmed: bool = False, *, context: RequestContext) -> dict:
        context = _identity(context)
        if not isinstance(query, str) or not query.strip():
            raise ValueError("query 不能为空")
        result = await run_sync(
            self.service.sop.handle, query.strip(), conversation_id, [],
            confirmed=confirmed, context=context,
        )
        return _result_dict(result)

    async def readonly_sql_query(self, question: str,
                                 *, context: RequestContext) -> dict:
        context = _identity(context)
        if not context.can("sql:read"):
            raise PermissionError("MCP 请求缺少 sql:read 权限")
        if not isinstance(question, str) or not question.strip():
            raise ValueError("question 不能为空")
        result = await run_sync(self.service.nl2sql.answer,
                                question.strip(), f"mcp:{context.tenant_id}:{context.user_id}",
                                context=context)
        return _result_dict(result)
