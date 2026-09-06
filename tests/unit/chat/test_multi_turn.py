"""多轮 NL2SQL 和换题隔离测试。"""
from app.chat.adapters.memory_conversation_store import MemoryConversationStore
from app.chat.adapters.memory_session_state_store import MemorySessionStateStore
from app.chat.adapters.memory_schema_catalog import MemorySchemaCatalog, SchemaDomain
from app.chat.adapters.memory_sop_store import MemorySopStore
from app.chat.application.chat_service import ChatService
from app.chat.application.context import RequestContext
from app.chat.application.conversation_understanding import RuleConversationUnderstanding
from app.chat.application.context_builder import ContextBuilder
from app.chat.application.intent_router import RuleIntentRouter
from app.chat.application.nl2sql.nl2sql_service import Nl2SqlService
from app.chat.application.nl2sql.row_policy import BoundPolicy
from app.chat.application.rag_answerer import RagAnswerer
from app.chat.application.sop.sop_service import SopService
from app.chat.bootstrap.defaults import default_sops
from app.chat.domain.models import SqlResult


class FakeLLM:
    def __init__(self):
        self.prompts = []

    def chat(self, messages):
        prompt = messages[-1].content
        self.prompts.append(prompt)
        if "只生成单条 SELECT" in prompt:
            return "```sql\nSELECT SUM(budget) AS total_budget FROM procurement_requests\n```"
        return '{"answer":"已根据当前结果回答","used_citations":[],"grounded":false}'

    def close(self):
        pass


class EmptyRetriever:
    def retrieve(self, *args, **kwargs):
        return []

    def close(self):
        pass


class FakeSql:
    def __init__(self):
        self.sql = []
        self.policies = []

    def query(self, sql, **kwargs):
        self.sql.append(sql)
        self.policies.append(kwargs.get("row_policies") or ())
        return SqlResult(("total_budget",), ((250000.0,),), f"q-{len(self.sql)}", 1)


def _service(llm, sql):
    catalog = MemorySchemaCatalog([SchemaDomain(
        "procurement", "采购数据", frozenset({"procurement_requests"}),
        ("采购", "预算", "采购申请"),
        columns={"procurement_requests": frozenset({"budget"})},
    )])
    return ChatService(
        RuleIntentRouter(), MemoryConversationStore(),
        RagAnswerer(EmptyRetriever(), llm, ContextBuilder()),
        SopService(MemorySopStore(default_sops()), llm, EmptyRetriever()),
        Nl2SqlService(llm, catalog, sql),
        session_state=MemorySessionStateStore(),
        understanding=RuleConversationUnderstanding(),
    )


_CTX = RequestContext(
    trace_id="multi-turn-test", tenant_id="tenant-test", user_id="user-test-001",
    authenticated=True, permissions=("chat:ask", "sql:read"),
)


def test_extract_sql_supports_common_fences():
    from app.chat.application.nl2sql.nl2sql_service import Nl2SqlService
    svc = Nl2SqlService.__new__(Nl2SqlService)
    assert svc._extract_sql("```mysql\nSELECT 1\n```") == "SELECT 1"
    assert svc._extract_sql("```sql\nSELECT 1\n```") == "SELECT 1"
    assert svc._extract_sql("SELECT 1") == "SELECT 1"


def test_nl2sql_follow_up_reuses_domain_and_requeries():
    llm, sql = FakeLLM(), FakeSql()
    service = _service(llm, sql)
    first = service.ask("查询本月采购申请总预算", conversation_id="c", context=_CTX)
    second = service.ask("其中华东地区有多少", conversation_id="c", context=_CTX)
    assert first.mode.value == "nl2sql"
    assert second.mode.value == "nl2sql"
    assert len(sql.sql) == 2
    # 租户条件改为参数化策略传递，不再作为字面量写进 SQL 文本。
    assert all("tenant_id = 'tenant-test'" not in item for item in sql.sql)
    tenant_params = tuple(
        p.params[0]
        for per_table in sql.policies
        for policies in per_table.values()
        for p in policies
        if p.sql == "tenant_id = %s"
    )
    assert tenant_params == ("tenant-test", "tenant-test")
    assert any("上轮已确认的问题" in prompt for prompt in llm.prompts)


def test_new_topic_does_not_reuse_previous_sql_domain():
    llm, sql = FakeLLM(), FakeSql()
    service = _service(llm, sql)
    service.ask("查询本月采购申请总预算", conversation_id="c", context=_CTX)
    result = service.ask("RAG 是什么", conversation_id="c", context=_CTX)
    assert result.mode.value == "knowledge_qa"


def test_pending_domain_answer_replays_original_query():
    llm, sql = FakeLLM(), FakeSql()
    service = _service(llm, sql)
    first = service.ask("统计本月数据", conversation_id="pending", context=_CTX)
    assert first.status.value == "clarification"
    assert len(sql.sql) == 0
    state = service.session_state.get("pending", context=_CTX)
    assert state.extra["pending_domain"]["question"] == "统计本月数据"

    second = service.ask("采购", conversation_id="pending", context=_CTX)
    assert second.mode.value == "nl2sql"
    assert len(sql.sql) == 1
    state = service.session_state.get("pending", context=_CTX)
    assert "pending_domain" not in state.extra
