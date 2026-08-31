"""Unified chat orchestration: route intent, dispatch to an isolated executor,
persist conversation, and surface citations/structured outputs."""
from ..domain.models import ChatMessage, ChatResult, ChatStatus, Intent
from .context import RequestContext
from .ports import ConversationStore, IntentRouter
from .rag_answerer import RagAnswerer
from .sop.sop_service import SopService
from .nl2sql.nl2sql_service import Nl2SqlService


class ChatService:
    def __init__(self, router: IntentRouter, conversation: ConversationStore,
                 rag: RagAnswerer, sop: SopService, nl2sql: Nl2SqlService):
        self.router = router
        self.conversation = conversation
        self.rag = rag
        self.sop = sop
        self.nl2sql = nl2sql

    def ask(self, question: str, *, conversation_id: str = "default",
            confirmed: bool = False,
            context: RequestContext | None = None) -> ChatResult:
        context = context or RequestContext()
        self.conversation.get_or_create(conversation_id)
        history = self.conversation.recent(conversation_id, limit=10)
        decision = self.router.route(question, history)
        if decision.intent == Intent.CLARIFICATION:
            result = ChatResult(
                answer="请说得更明确一些：是想查询业务数据、了解流程步骤，还是基于文档问答？",
                status=ChatStatus.CLARIFICATION, mode=Intent.CLARIFICATION,
                conversation_id=conversation_id, warnings=("clarification",),
            )
        elif decision.intent == Intent.SOP:
            result = self.sop.handle(question, conversation_id, history,
                                     confirmed=confirmed, context=context)
        elif decision.intent == Intent.NL2SQL:
            result = self.nl2sql.answer(question, conversation_id, context=context)
        else:  # KNOWLEDGE_QA, MIXED, CHITCHAT all fall back to RAG
            result = self.rag.answer(question, conversation_id, history, context=context)

        if not result.trace_id:
            result = ChatResult(
                answer=result.answer, status=result.status, mode=result.mode,
                conversation_id=result.conversation_id,
                citations=result.citations, sql=result.sql, sop=result.sop,
                warnings=result.warnings, trace_id=context.trace_id,
            )
        self.conversation.append(conversation_id, ChatMessage("user", question))
        self.conversation.append(conversation_id, ChatMessage(
            "assistant", f"{result.answer}\nmode={result.mode.value}"))
        return result
