"""Unified chat orchestration: route intent, dispatch to an isolated executor,
persist conversation, and surface citations/structured outputs."""
import uuid

import structlog

from ..domain.models import (AuditEvent, ChatMessage, ChatResult, ChatStatus, Intent,
                             IntentDecision, SessionState)
from .context import RequestContext
from .ports import AuditLogger, ConversationStore, IntentRouter
from .rag_answerer import RagAnswerer
from .sop.sop_service import SopService
from .nl2sql.nl2sql_service import Nl2SqlService

logger = structlog.get_logger(__name__)


class ChatService:
    def __init__(self, router: IntentRouter, conversation: ConversationStore,
                 rag: RagAnswerer, sop: SopService, nl2sql: Nl2SqlService,
                 audit: AuditLogger | None = None,
                 session_state=None, question_resolver=None):
        self.router = router
        self.conversation = conversation
        self.rag = rag
        self.sop = sop
        self.nl2sql = nl2sql
        self.audit = audit
        self.session_state = session_state
        self.question_resolver = question_resolver

    def _audit(self, event: AuditEvent) -> None:
        if self.audit is None:
            return
        try:
            self.audit.record(event)
        except Exception:
            logger.exception("chat_audit_record_failed", event_id=event.event_id,
                             trace_id=event.trace_id, stage=event.stage)

    def ask(self, question: str, *, conversation_id: str = "default",
            confirmed: bool = False,
            context: RequestContext | None = None) -> ChatResult:
        context = context or RequestContext()
        start_event_id = str(uuid.uuid4())
        self._audit(AuditEvent(
            event_id=start_event_id, trace_id=context.trace_id, stage="request",
            status="started", tenant_id=context.tenant_id, user_id=context.user_id,
            conversation_id=conversation_id,
            payload={"question": question},
        ))
        self.conversation.get_or_create(conversation_id, context=context)
        history = self.conversation.recent(conversation_id, limit=10, context=context)
        state = None
        if self.session_state is not None:
            state = self.session_state.get(conversation_id, context=context)

        resolved = question
        intent_hint = None
        if self.question_resolver is not None:
            r = self.question_resolver.resolve(question, history, state)
            resolved = r.question
            intent_hint = r.intent_hint
            if r.needs_clarification:
                return ChatResult(
                    answer="请说得更明确一些，以便我基于上次对话继续。",
                    status=ChatStatus.CLARIFICATION, mode=Intent.CLARIFICATION,
                    conversation_id=conversation_id,
                    warnings=("clarification",), trace_id=context.trace_id,
                )

        if intent_hint is not None:
            decision = IntentDecision(intent=intent_hint, confidence=1.0, reason="沿用会话状态")
        else:
            decision = self.router.route(resolved, history)
        if decision.intent == Intent.CLARIFICATION:
            result = ChatResult(
                answer="请说得更明确一些：是想查询业务数据、了解流程步骤，还是基于文档问答？",
                status=ChatStatus.CLARIFICATION, mode=Intent.CLARIFICATION,
                conversation_id=conversation_id, warnings=("clarification",),
            )
        elif decision.intent == Intent.SOP:
            result = self.sop.handle(resolved, conversation_id, history,
                                     confirmed=confirmed, context=context)
        elif decision.intent == Intent.NL2SQL:
            result = self.nl2sql.answer(resolved, conversation_id, context=context,
                                        state=state)
        else:  # KNOWLEDGE_QA, MIXED, CHITCHAT all fall back to RAG
            result = self.rag.answer(resolved, conversation_id, history, context=context)

        self._update_session_state(conversation_id, decision.intent, result, context)

        if not result.trace_id:
            result = ChatResult(
                answer=result.answer, status=result.status, mode=result.mode,
                conversation_id=result.conversation_id,
                citations=result.citations, sql=result.sql, sop=result.sop,
                warnings=result.warnings, trace_id=context.trace_id,
                citation_audit=result.citation_audit,
            )
        self.conversation.append(conversation_id, ChatMessage("user", question), context=context)
        self.conversation.append(conversation_id, ChatMessage(
            "assistant", f"{result.answer}\nmode={result.mode.value}"), context=context)
        citation_audit = None
        if result.citation_audit is not None:
            citation_audit = {
                "sent": list(result.citation_audit.sent),
                "used": list(result.citation_audit.used),
                "unused": list(result.citation_audit.unused),
                "grounded": result.citation_audit.grounded,
            }
        self._audit(AuditEvent(
            event_id=str(uuid.uuid4()), trace_id=context.trace_id, stage="request",
            status=result.status.value, tenant_id=context.tenant_id, user_id=context.user_id,
            conversation_id=conversation_id, mode=result.mode.value,
            payload={"question": question, "answer": result.answer,
                     "warnings": list(result.warnings), "citation_audit": citation_audit,
                     "sent": citation_audit["sent"] if citation_audit else [],
                     "used": citation_audit["used"] if citation_audit else [],
                     "unused": citation_audit["unused"] if citation_audit else [],
                     "grounded": citation_audit["grounded"] if citation_audit else False},
        ))
        return result

    def _update_session_state(self, conversation_id, intent, result, context):
        if self.session_state is None:
            return
        previous = None
        getter = getattr(self.session_state, "get", None)
        if callable(getter):
            previous = getter(conversation_id, context=context)
        sql = result.sql or {}
        sop = result.sop or {}
        domain = sql.get("domain") or (previous.last_domain if previous else None)
        state = SessionState(
            last_intent=intent,
            last_domain=domain,
            last_query_id=sql.get("query_id") if sql else None,
            current_sop_id=sop.get("sop_id") if sop else None,
            current_sop_version=sop.get("version") if sop else None,
            current_step_id=sop.get("current_step") if sop else None,
            extra={},
            version_no=(previous.version_no if previous else 1),
        )
        saver = getattr(self.session_state, "save", None)
        if callable(saver):
            saver(conversation_id, state, context=context)

    def close(self) -> None:
        """Release any resources owned by executors (LLM, retriever, stores)."""
        for resource in (self.rag, self.sop, self.nl2sql):
            closer = getattr(resource, "close", None)
            if callable(closer):
                closer()
        for store in (self.conversation, self.audit):
            closer = getattr(store, "close", None)
            if callable(closer):
                closer()
