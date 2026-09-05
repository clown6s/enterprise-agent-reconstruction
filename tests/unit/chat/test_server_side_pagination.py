"""服务端状态分页：前端只发自然语言“下一页”，不传 cursor/page_size。"""
from app.chat.application.chat_service import ChatService
from app.chat.application.context import RequestContext
from app.chat.application.nl2sql.nl2sql_service import Nl2SqlService
from app.chat.application.rag_answerer import RagAnswerer
from app.chat.application.sop.sop_service import SopService
from app.chat.adapters.memory_conversation_store import MemoryConversationStore
from app.chat.adapters.memory_session_state_store import MemorySessionStateStore
from app.chat.domain.models import Intent, IntentDecision, SqlResult


class _Router:
    def route(self, query, history=None):
        return IntentDecision(Intent.NL2SQL, 1.0, "test")


class _LLM:
    def __init__(self):
        self.calls = 0

    def chat(self, messages):
        prompt = messages[-1].content
        if "单条 SELECT" in prompt:
            self.calls += 1
            return "```sql\nSELECT created_at, order_id FROM orders\n```"
        return "查询结果如上。"


class _Catalog:
    def resolve_domain(self, query, *, context): return "orders"
    def describe(self, domain, *, context):
        return "orders(created_at, order_id, amount)"
    def allowed_tables(self, domain, *, context): return {"orders"}
    def allowed_columns(self, domain, *, context):
        return {"orders": {"created_at", "order_id", "amount"}}
    def blocked_columns(self, domain, *, context): return {}
    def domain_limits(self, domain, *, context): return 1000, 10
    def row_policies(self, domain, table_name, *, context): return ()


class _Executor:
    def __init__(self):
        self.sqls = []

    def query(self, sql, **kwargs):
        self.sqls.append(sql)
        rows = [("2026-09-01 09:00:00", f"O{i:03d}") for i in range(20)]
        return SqlResult(("created_at", "order_id"), tuple(rows), "q1", 20,
                         truncated=True)


def _service():
    llm = _LLM()
    conversation = MemoryConversationStore()
    session = MemorySessionStateStore()
    executor = _Executor()
    nl2sql = Nl2SqlService(llm, _Catalog(), executor)
    chat = ChatService(
        router=_Router(), conversation=conversation, rag=None, sop=None, nl2sql=nl2sql,
        session_state=session, understanding=None, question_resolver=None,
    )
    return chat, llm, executor, session


def test_next_page_reuses_sql_without_llm():
    ctx = RequestContext(tenant_id="t1", user_id="u1", authenticated=True)
    chat, llm, executor, session = _service()

    first = chat.ask("列出最近的订单", conversation_id="c1", context=ctx)
    assert first.status.value == "answered"
    assert llm.calls == 1
    assert len(executor.sqls) == 1
    # 首页返回里不能携带 base_sql 私有字段
    assert "_pagination_base_sql" not in first.sql

    calls_before = llm.calls
    second = chat.ask("下一页", conversation_id="c1", context=ctx)
    assert second.status.value == "answered"
    # 下一页不能重新调用模型
    assert llm.calls == calls_before
    assert len(executor.sqls) == 2
    # 下一页复用同一基础 SQL，并追加服务端游标条件。
    assert "FROM orders" in executor.sqls[1]
    assert "WHERE created_at < __NL2SQL_CURSOR_0__" in executor.sqls[1]
    assert "ORDER BY created_at DESC, order_id DESC LIMIT 21" in executor.sqls[1]

    # 上一页回到第 1 页：不再追加游标条件，不调用 LLM。
    before = llm.calls
    prev = chat.ask("上一页", conversation_id="c1", context=ctx)
    assert prev.status.value == "answered"
    assert llm.calls == before
    assert "WHERE created_at <" not in executor.sqls[-1]
    assert "ORDER BY created_at DESC, order_id DESC LIMIT 21" in executor.sqls[-1]
