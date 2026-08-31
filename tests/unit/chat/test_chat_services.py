from app.chat.adapters.memory_conversation_store import MemoryConversationStore
from app.chat.adapters.memory_schema_catalog import MemorySchemaCatalog, SchemaDomain
from app.chat.adapters.memory_sop_store import MemorySopStore
from app.chat.application.chat_service import ChatService
from app.chat.application.context_builder import ContextBuilder
from app.chat.application.intent_router import RuleIntentRouter
from app.chat.application.nl2sql.nl2sql_service import Nl2SqlService
from app.chat.application.rag_answerer import RagAnswerer
from app.chat.application.sop.sop_engine import SopEngine
from app.chat.application.sop.sop_service import SopService
from app.chat.bootstrap.defaults import default_sops
from app.chat.domain.models import RetrievalItem, SqlResult


class FakeLLM:
    def chat(self, messages):
        prompt = messages[-1].content
        if "只生成单条 SELECT" in prompt:
            return "```sql\nSELECT amount FROM orders\n```"
        return "基于参考资料的回答 [1]"

    def close(self):
        pass


class FakeRetriever:
    def retrieve(self, query, *, top_k=5, filter=""):
        return [RetrievalItem("可信资料", 0.9, "doc-1", "doc-1:1", 2)]

    def close(self):
        pass


class FakeSql:
    def query(self, sql, *, timeout_s=10.0, max_rows=1000):
        return SqlResult(("amount",), ((100,),), "q-1", 1)


def _service():
    llm = FakeLLM()
    retriever = FakeRetriever()
    catalog = MemorySchemaCatalog([SchemaDomain(
        "orders", "orders(amount)", frozenset({"orders"}), ("订单",))])
    return ChatService(
        RuleIntentRouter(), MemoryConversationStore(),
        RagAnswerer(retriever, llm, ContextBuilder()),
        SopService(MemorySopStore(default_sops()), llm, retriever),
        Nl2SqlService(llm, catalog, FakeSql()),
    )


def test_chat_routes_rag_sop_and_sql():
    service = _service()
    assert service.ask("报销标准是什么", conversation_id="r").mode.value == "knowledge_qa"
    assert service.ask("报销流程下一步怎么做", conversation_id="s").mode.value == "sop"
    assert service.ask("统计订单金额", conversation_id="q").mode.value == "nl2sql"


def test_sql_guard_rejects_write():
    from app.chat.application.nl2sql.sql_guard import validate_sql
    import pytest
    with pytest.raises(Exception):
        validate_sql("DELETE FROM orders", allowed_tables={"orders"})


def test_sop_engine_requires_confirmation():
    definition = default_sops()[0]
    engine = SopEngine()
    state = engine.begin(definition)          # s1
    state = engine.advance(definition, state)  # s2
    state = engine.advance(definition, state)  # s3 (requires confirmation)
    # 在 s3 上未经确认继续 → 挂起等待确认
    state = engine.advance(definition, state)
    assert state.awaiting_confirmation is True
    # 明确确认后放行
    state = engine.advance(definition, state, confirmed=True)
    assert state.awaiting_confirmation is False
