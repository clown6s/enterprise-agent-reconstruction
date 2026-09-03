"""MCP server smoke tests over the in-memory transport."""
import pytest

from app.chat.application.chat_service import ChatService
from app.chat.application.context_builder import ContextBuilder
from app.chat.application.intent_router import RuleIntentRouter
from app.chat.application.nl2sql.nl2sql_service import Nl2SqlService
from app.chat.application.rag_answerer import RagAnswerer
from app.chat.application.sop.sop_service import SopService
from app.chat.adapters.memory_conversation_store import MemoryConversationStore
from app.chat.adapters.memory_schema_catalog import MemorySchemaCatalog, SchemaDomain
from app.chat.adapters.memory_sop_store import MemorySopStore
from app.chat.bootstrap.defaults import default_sops
from app.chat.domain.models import RetrievalItem, SqlResult
from app.chat.mcp.config import McpPolicy
from app.chat.mcp.server import build_server


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
    def query(self, sql, *, timeout_s=10.0, max_rows=1000, row_policies=()):
        return SqlResult(("amount",), ((100,),), "q-1", 1)


def _service() -> ChatService:
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


@pytest.fixture
def server():
    return build_server(_service(), policy=McpPolicy())


def _tool_names(server) -> set[str]:
    return {t.name for t in server._tool_manager.list_tools()}


def test_server_registers_all_tools(server):
    assert _tool_names(server) == {
        "chat_ask", "document_search", "sop_get_step", "readonly_sql_query",
    }


def test_server_respects_tool_allowlist():
    server = build_server(_service(), policy=McpPolicy(
        enabled_tools=("chat_ask",)))
    assert _tool_names(server) == {"chat_ask"}


def test_chat_tools_ask_returns_structured():
    import asyncio
    from app.chat.application.context import RequestContext
    from app.chat.mcp.tools import ChatTools
    tools = ChatTools(_service())
    context = RequestContext(tenant_id="ten-1", user_id="u-1", authenticated=True)
    result = asyncio.run(
        tools.chat_ask("报销标准是什么", "c1", context=context))
    assert result["mode"] == "knowledge_qa"
    assert "citations" in result and result["conversation_id"] == "c1"


def test_chat_tools_rejects_missing_identity():
    import asyncio
    from app.chat.application.context import RequestContext
    from app.chat.mcp.tools import ChatTools
    tools = ChatTools(_service())
    with pytest.raises(PermissionError):
        asyncio.run(tools.chat_ask(
            "报销标准是什么", "c1", context=RequestContext()))


def test_readonly_sql_requires_sql_read_permission():
    import asyncio
    from app.chat.application.context import RequestContext
    from app.chat.mcp.tools import ChatTools
    tools = ChatTools(_service())
    context = RequestContext(tenant_id="ten-1", user_id="u-1", authenticated=True)
    with pytest.raises(PermissionError, match="sql:read"):
        asyncio.run(tools.readonly_sql_query("查询订单", context=context))
