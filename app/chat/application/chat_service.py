"""统一聊天编排：路由意图、分派到隔离执行器、持久化会话，并返回引用及结构化结果。"""
import uuid

import structlog

from ..domain.models import (AuditEvent, ChatMessage, ChatResult, ChatStatus, Intent,
                             ConversationRelation, IntentDecision, SessionState)
from .context import RequestContext
from .ports import (AuditLogger, ConversationStore, ConversationUnderstanding,
                    IntentRouter, SessionStateStore)
from .rag_answerer import RagAnswerer
from .sop.sop_service import SopService
from .nl2sql.nl2sql_service import Nl2SqlService

logger = structlog.get_logger(__name__)


class ChatService:
    _PAGE_SIZE = 5
    _NEXT_PAGE_WORDS = frozenset({"下一页", "下页", "继续", "再来一页"})
    _PREVIOUS_PAGE_WORDS = frozenset({"上一页", "上页"})

    def __init__(self, router: IntentRouter, conversation: ConversationStore,
                 rag: RagAnswerer, sop: SopService, nl2sql: Nl2SqlService,
                 audit: AuditLogger | None = None,
                 session_state: SessionStateStore | None = None,
                 question_resolver=None,
                 understanding: ConversationUnderstanding | None = None):
        self.router = router
        self.conversation = conversation
        self.rag = rag
        self.sop = sop
        self.nl2sql = nl2sql
        self.audit = audit
        self.session_state = session_state
        self.question_resolver = question_resolver
        self.understanding = understanding

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

        direction = self._pagination_direction(question)
        if direction is not None:
            # 翻页指令彻底前置：只查服务端分页状态，绝不进入数据域解析/意图路由。
            pagination = self._pagination_from_state(state, question, context)
            if pagination is None:
                return ChatResult(
                    answer="当前没有可继续的分页查询，请先发起一次业务查询。",
                    status=ChatStatus.CLARIFICATION, mode=Intent.NL2SQL,
                    conversation_id=conversation_id, warnings=("pagination_not_started",),
                    trace_id=context.trace_id,
                )
            result = self.nl2sql.answer(
                "", conversation_id, context=context,
                page_size=pagination.get("page_size"),
                cursor=pagination.get("cursor"),
                pagination_state=pagination,
            )
            result = ChatResult(
                answer=result.answer, status=result.status, mode=result.mode,
                conversation_id=result.conversation_id,
                citations=result.citations, sql=result.sql, sop=result.sop,
                warnings=result.warnings, trace_id=context.trace_id,
                citation_audit=result.citation_audit,
            )
            self._update_session_state(
                conversation_id, Intent.NL2SQL, result, context,
                resolved_question="下一页", pagination_direction=direction,
            )
            if result.sql is not None:
                result.sql.pop("_pagination_base_sql", None)
                result.sql.pop("cursor", None)
                result.sql.pop("page_size", None)
                result.sql.pop("next_cursor", None)
            return result

        resolved = question
        relation = None
        understanding = None
        if self.understanding is not None:
            understanding = self.understanding.understand(question, history, state)
            resolved = understanding.question or question
            relation = understanding.relation
            if understanding.needs_clarification:
                return ChatResult(
                    answer="请补充你要继续的主题或具体问题。",
                    status=ChatStatus.CLARIFICATION, mode=Intent.CLARIFICATION,
                    conversation_id=conversation_id,
                    warnings=("clarification",), trace_id=context.trace_id,
                )
        elif self.question_resolver is not None:
            # 兼容旧 resolver；其 intent_hint 只作为改写提示，不能强制路由。
            resolved = self.question_resolver.resolve(question, history, state).question or question

        # 业务意图只由当前独立问题决定；不会被上一轮 last_intent 覆盖。
        decision = self.router.route(resolved, [])
        if relation is not None and relation.value == "mixed":
            decision = IntentDecision(Intent.MIXED, decision.confidence, "会话理解识别为混合任务")
        if decision.intent == Intent.CLARIFICATION:
            result = ChatResult(
                answer="请说得更明确一些：是想查询业务数据、了解流程步骤，还是基于文档问答？",
                status=ChatStatus.CLARIFICATION, mode=Intent.CLARIFICATION,
                conversation_id=conversation_id, warnings=("clarification",),
            )
        elif decision.intent == Intent.SOP:
            result = self.sop.handle(
                resolved, conversation_id, history, confirmed=confirmed,
                context=context,
                continue_state=(relation == ConversationRelation.FOLLOW_UP),
            )
        elif decision.intent == Intent.NL2SQL:
            result = self.nl2sql.answer(
                resolved, conversation_id, context=context,
                state=(state if relation == ConversationRelation.FOLLOW_UP else None),
                page_size=self._PAGE_SIZE,
            )
        elif decision.intent == Intent.MIXED and understanding is not None:
            result = self._handle_mixed(
                understanding.subtasks, conversation_id, context, history,
                confirmed=confirmed)
        else:  # KNOWLEDGE_QA / CHITCHAT
            # history 只供会话理解；RAG 的 LLM 只看当前问题和本轮片段。
            result = self.rag.answer(resolved, conversation_id, [], context=context)

        self._update_session_state(
            conversation_id, decision.intent, result, context,
            relation=relation.value if relation else None,
            topic=understanding.topic if understanding else None,
            resolved_question=resolved,
            pagination_direction=self._pagination_direction(question),
        )
        # 基础 SQL 只保存在服务端会话状态，不暴露给前端。
        if result.sql is not None:
            result.sql.pop("_pagination_base_sql", None)
            # 分页游标只保存在服务端，不暴露给前端。
            result.sql.pop("cursor", None)
            result.sql.pop("page_size", None)
            result.sql.pop("next_cursor", None)

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
                "sent_details": list(result.citation_audit.sent_details),
                "used_details": list(result.citation_audit.used_details),
                "unused_details": list(result.citation_audit.unused_details),
            }
        # NL2SQL 在 MySQL 中有专属的审计行。将其视为尽力而为的
        # 副作用：AuditLogger 失败绝不能改变回答路径。
        if result.mode == Intent.NL2SQL:
            sql_info = result.sql or {}
            self._audit(AuditEvent(
                event_id=str(uuid.uuid4()), trace_id=context.trace_id,
                stage="nl2sql", status=result.status.value,
                tenant_id=context.tenant_id, user_id=context.user_id,
                conversation_id=conversation_id, mode=result.mode.value,
                payload={
                    "question": question,
                    "domain": sql_info.get("domain"),
                    "sql": sql_info.get("query"),
                    "query_id": sql_info.get("query_id"),
                    "columns": sql_info.get("columns", []),
                    "row_count": sql_info.get("row_count"),
                    "truncated": bool(sql_info.get("truncated", False)),
                    "generation_status": sql_info.get("generation_status", "executed"),
                    "guard_status": sql_info.get("guard_status", "allowed"),
                    "execution_status": sql_info.get("execution_status", "success"),
                    "execution_retried": bool(sql_info.get("execution_retried", False)),
                },
            ))
        self._audit(AuditEvent(
            event_id=str(uuid.uuid4()), trace_id=context.trace_id, stage="request",
            status=result.status.value, tenant_id=context.tenant_id, user_id=context.user_id,
            conversation_id=conversation_id, mode=result.mode.value,
            payload={"question": question, "answer": result.answer,
                     "warnings": list(result.warnings), "citation_audit": citation_audit,
                     "sent": citation_audit["sent"] if citation_audit else [],
                     "used": citation_audit["used"] if citation_audit else [],
                     "unused": citation_audit["unused"] if citation_audit else [],
                     "grounded": citation_audit["grounded"] if citation_audit else False,
                     "sent_details": (citation_audit["sent_details"] if citation_audit else []),
                     "used_details": (citation_audit["used_details"] if citation_audit else []),
                     "unused_details": (citation_audit["unused_details"] if citation_audit else [])},
        ))
        return result

    def _handle_mixed(self, subtasks, conversation_id, context, history,
                      confirmed):
        parts = []
        citations = []
        warnings = []
        sql = None
        sop = None
        for sub in subtasks:
            q = (sub.get("question") or "").strip()
            if not q:
                continue
            hint = sub.get("intent")
            if hint in (Intent.NL2SQL.value, "nl2sql"):
                r = self.nl2sql.answer(q, conversation_id, context=context)
            elif hint in (Intent.SOP.value, "sop"):
                r = self.sop.handle(q, conversation_id, [], confirmed=confirmed,
                                    context=context, continue_state=False)
            else:
                r = self.rag.answer(q, conversation_id, [], context=context)
            parts.append(r.answer)
            citations.extend(r.citations)
            warnings.extend(r.warnings)
            if r.sql:
                sql = r.sql
            if r.sop:
                sop = r.sop
        return ChatResult(
            answer="\n".join(parts) if parts else "未解析出可执行的子任务。",
            status=ChatStatus.ANSWERED if parts else ChatStatus.NO_CONTEXT,
            mode=Intent.MIXED, conversation_id=conversation_id,
            citations=tuple(citations), sql=sql, sop=sop,
            warnings=tuple(dict.fromkeys(warnings)), trace_id=context.trace_id,
        )

    def _pagination_payload(self, sql, context, previous=None, direction=None):
        """生成服务端分页状态，保存所有已访问页的起点。"""
        base = sql.get("_pagination_base_sql") if sql else None
        if not base or not context.tenant_id:
            return None
        old = (previous.extra.get("nl2sql_pagination")
               if previous and previous.extra else None)
        old = old if isinstance(old, dict) else {}
        history = list(old.get("history") or [None])
        current = int(old.get("current_page", 0))
        if direction == "next":
            next_cursor = sql.get("next_cursor")
            if current + 1 < len(history):
                current += 1
            elif next_cursor:
                history.append(next_cursor)
                current += 1
        elif direction == "previous" and current > 0:
            current -= 1
        return {
            "tenant_id": context.tenant_id,
            "user_id": context.user_id,
            "domain": sql.get("domain") or old.get("domain"),
            "base_sql": base,
            "cursor": history[current],
            "next_cursor": sql.get("next_cursor"),
            "page_size": sql.get("page_size") or old.get("page_size") or self._PAGE_SIZE,
            "has_more": bool(sql.get("truncated")),
            "history": history,
            "current_page": current,
        }

    def _pagination_from_state(self, state, question, context):
        """按固定方向从服务端分页历史取得目标页起点。"""
        direction = self._pagination_direction(question)
        if not direction or state is None or not state.extra:
            return None
        stored = state.extra.get("nl2sql_pagination")
        if not isinstance(stored, dict) or not stored.get("base_sql"):
            return None
        if stored.get("tenant_id") != context.tenant_id or stored.get("user_id") != context.user_id:
            return None
        history = list(stored.get("history") or [None])
        current = int(stored.get("current_page", 0))
        if direction == "next":
            if current + 1 < len(history):
                target = current + 1
            elif stored.get("has_more") and stored.get("next_cursor"):
                target = current + 1
                history.append(stored["next_cursor"])
            else:
                return None
        elif current > 0:
            target = current - 1
        else:
            return None
        result = dict(stored)
        result.update(cursor=history[target], history=history, current_page=target)
        return result

    @classmethod
    def _pagination_direction(cls, question: str) -> str | None:
        """用固定规则识别翻页方向，不做语义判断。"""
        q = (question or "").strip()
        if q in cls._NEXT_PAGE_WORDS:
            return "next"
        if q in cls._PREVIOUS_PAGE_WORDS:
            return "previous"
        return None

    @classmethod
    def _is_pagination_request(cls, question: str) -> bool:
        return cls._pagination_direction(question) is not None

    def _update_session_state(self, conversation_id, intent, result, context,
                              relation=None, topic=None, resolved_question=None,
                              pagination_direction=None):
        if self.session_state is None:
            return
        previous: SessionState | None = self.session_state.get(
            conversation_id, context=context)
        sql = result.sql or {}
        sop = result.sop or {}
        # 新主题不继承旧数据域；只有当前结果明确提供 domain 才保存。
        domain = sql.get("domain")
        if relation == "follow_up" and not domain and previous:
            domain = previous.last_domain
        state = SessionState(
            last_intent=intent,
            last_domain=domain,
            last_query_id=sql.get("query_id") if sql else None,
            current_sop_id=sop.get("sop_id") if sop else None,
            current_sop_version=sop.get("version") if sop else None,
            current_step_id=sop.get("current_step") if sop else None,
            extra={
                "topic": topic or (previous.extra.get("topic") if previous and relation == "follow_up" else None),
                "last_question": resolved_question,
                "relation": relation,
                "nl2sql_pagination": self._pagination_payload(
                    sql, context, previous=previous, direction=pagination_direction),
            },
            version_no=(previous.version_no if previous else 1),
        )
        if self.session_state is not None:
            self.session_state.save(conversation_id, state, context=context)

    def close(self) -> None:
        """释放执行器所持有的资源（LLM、检索器和存储）。"""
        for resource in (self.rag, self.sop, self.nl2sql):
            closer = getattr(resource, "close", None)
            if callable(closer):
                closer()
        for store in (self.conversation, self.audit):
            closer = getattr(store, "close", None)
            if callable(closer):
                closer()
