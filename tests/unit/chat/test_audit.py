import pytest

from app.chat.adapters.memory_conversation_store import MemoryConversationStore
from app.chat.application.chat_service import ChatService
from app.chat.application.context import RequestContext
from app.chat.application.context_builder import ContextBuilder
from app.chat.application.intent_router import RuleIntentRouter
from app.chat.application.nl2sql.nl2sql_service import Nl2SqlService
from app.chat.application.rag_answerer import RagAnswerer
from app.chat.application.sop.sop_service import SopService
from app.chat.adapters.memory_schema_catalog import MemorySchemaCatalog, SchemaDomain
from app.chat.adapters.memory_sop_store import MemorySopStore
from app.chat.bootstrap.defaults import default_sops
from app.chat.domain.models import Citation, RetrievalItem, SqlResult


class FakeAudit:
    def __init__(self):
        self.events = []
        self.fail = False

    def record(self, event):
        if self.fail:
            raise RuntimeError("audit down")
        self.events.append(event)

    def close(self):
        pass


class FakeLLM:
    def __init__(self, payload):
        self._payload = payload

    def chat(self, messages):
        if callable(self._payload):
            return self._payload(messages)
        return self._payload

    def close(self):
        pass


class FakeRetriever:
    def __init__(self, items=None):
        self._items = items or [RetrievalItem("资料A", .9, "d1", "d1:1", 1),
                                RetrievalItem("资料B", .8, "d1", "d1:2", 2)]
    def retrieve(self, *a, **k):
        return self._items
    def close(self):
        pass


class FakeSql:
    def query(self, sql, **k):
        return SqlResult(("a",), ((1,),), "q1", 1)


def _service(audit, llm):
    rt = FakeRetriever()
    catalog = MemorySchemaCatalog([SchemaDomain("orders", "orders", frozenset({"orders"}), ("订单",))])
    return ChatService(
        RuleIntentRouter(), MemoryConversationStore(),
        RagAnswerer(rt, llm, ContextBuilder()),
        SopService(MemorySopStore(default_sops()), llm, rt),
        Nl2SqlService(llm, catalog, FakeSql()),
        audit=audit,
    )


_CTX = RequestContext(tenant_id="t", user_id="u", authenticated=True, trace_id="tr-1")


def test_chat_service_emits_start_and_end_audit():
    audit = FakeAudit()
    svc = _service(audit, FakeLLM('{"answer":"答案","used_citations":[1],"grounded":true}'))
    result = svc.ask("报销标准是什么", conversation_id="c", context=_CTX)
    stages = [e.stage for e in audit.events]
    assert stages.count("request") == 2
    assert all(e.tenant_id == "t" and e.user_id == "u" for e in audit.events)
    assert result.trace_id == "tr-1"


def test_structured_rag_selects_only_used_citations():
    audit = FakeAudit()
    svc = _service(audit, FakeLLM('{"answer":"答案","used_citations":[2],"grounded":true}'))
    result = svc.ask("报销标准是什么", conversation_id="c", context=_CTX)
    # 只返回了引用 #2，而不是两个。
    assert [c.chunk_id for c in result.citations] == ["d1:2"]
    assert result.citation_audit is not None
    assert result.citation_audit.sent == (1, 2)
    assert result.citation_audit.used == (2,)
    assert result.citation_audit.unused == (1,)


def test_unstructured_legacy_marks_used_via_markers():
    audit = FakeAudit()
    svc = _service(audit, FakeLLM("答案基于资料 [1]"))
    result = svc.ask("报销标准是什么", conversation_id="c", context=_CTX)
    assert [c.chunk_id for c in result.citations] == ["d1:1"]
    assert "llm_response_not_structured" in result.warnings


def test_audit_failure_does_not_break_result():
    audit = FakeAudit()
    audit.fail = True
    svc = _service(audit, FakeLLM('{"answer":"答案","used_citations":[1],"grounded":true}'))
    result = svc.ask("报销标准是什么", conversation_id="c", context=_CTX)
    assert result.status.value == "answered"


def test_audit_records_routing_evidence_for_nl2sql():
    from app.chat.application.chat_service import ChatService
    from app.chat.application.context import RequestContext
    from app.chat.application.context_builder import ContextBuilder
    from app.chat.application.rag_answerer import RagAnswerer
    from app.chat.application.sop.sop_service import SopService
    from app.chat.application.nl2sql.nl2sql_service import Nl2SqlService
    from app.chat.adapters.memory_schema_catalog import MemorySchemaCatalog, SchemaDomain
    class _SqlLlm:
        def chat(self, messages):
            if "只生成单条 SELECT" in messages[-1].content:
                return "SELECT amount FROM orders"
            return '{"answer":"答案","used_citations":[1],"grounded":true}'
        def close(self): pass
    audit = FakeAudit()
    retriever = FakeRetriever()
    llm = _SqlLlm()
    catalog = MemorySchemaCatalog([SchemaDomain(
        "orders", "订单", frozenset({"orders"}), ("订单",),
        columns={"orders": frozenset({"amount"})})])
    svc = ChatService(
        RuleIntentRouter(), MemoryConversationStore(),
        RagAnswerer(retriever, llm, ContextBuilder()),
        SopService(MemorySopStore(default_sops()), llm),
        Nl2SqlService(llm, catalog, FakeSql()),
        audit=audit,
    )
    svc.ask("统计本月订单金额", conversation_id="c", context=_CTX)
    end = [e for e in audit.events if e.stage == "request"][-1]
    routing = end.payload.get("routing", {})
    assert routing["decision"] == "nl2sql"
    assert routing["preflight"] == "resolved"
    assert routing["domain"] == "orders"
    assert routing["business_domain"] is True


def test_audit_records_general_fallback_flag():
    from app.chat.application.general_qa import GeneralQaAnswerer
    from app.chat.application.chat_service import ChatService
    from app.chat.application.context import RequestContext
    from app.chat.application.context_builder import ContextBuilder
    from app.chat.application.rag_answerer import RagAnswerer
    from app.chat.application.sop.sop_service import SopService
    from app.chat.application.nl2sql.nl2sql_service import Nl2SqlService
    from app.chat.adapters.memory_schema_catalog import MemorySchemaCatalog
    from app.chat.domain.models import Intent
    class _EmptyRetriever:
        def retrieve(self, *a, **k): return []
        def close(self): pass
    audit = FakeAudit()
    llm = FakeLLM('{"answer":"答案","used_citations":[1],"grounded":true}')
    retriever = _EmptyRetriever()
    svc = ChatService(
        RuleIntentRouter(), MemoryConversationStore(),
        RagAnswerer(retriever, llm, ContextBuilder()),
        SopService(MemorySopStore(default_sops()), llm),
        Nl2SqlService(llm, MemorySchemaCatalog([]), FakeSql()),
        audit=audit, general_qa=GeneralQaAnswerer(llm),
    )
    svc.ask("向量表示的机制是什么", conversation_id="g", context=_CTX)
    end = [e for e in audit.events if e.stage == "request"][-1]
    routing = end.payload.get("routing", {})
    assert routing["general_fallback"] is True
    assert routing["decision"] == "knowledge_qa"