"""Chat composition root: concrete adapters are wired here only."""
from .config import read_settings
from .defaults import default_schema_domains, default_sops
from ..adapters.ingestion_retriever import IngestionRetriever
from ..adapters.memory_conversation_store import MemoryConversationStore
from ..adapters.memory_schema_catalog import MemorySchemaCatalog
from ..adapters.memory_sop_store import MemorySopStore
from ..adapters.mysql_readonly_executor import MysqlReadonlyExecutor
from ..adapters.openai_compat_chat import OpenAiCompatChat
from ..application.chat_service import ChatService
from ..application.context_builder import ContextBuilder
from ..application.intent_router import RuleIntentRouter
from ..application.nl2sql.nl2sql_service import Nl2SqlService
from ..application.rag_answerer import RagAnswerer
from ..application.sop.sop_service import SopService


def build_chat(*, retriever, llm=None, conversation=None,
               sop_store=None, schema_catalog=None, sql_executor=None) -> ChatService:
    settings = read_settings()
    llm = llm or OpenAiCompatChat(
        settings.api_key, base_url=settings.base_url, model=settings.model,
        temperature=settings.temperature, max_tokens=settings.max_tokens,
    )
    conversation = conversation or MemoryConversationStore()
    sop_store = sop_store or MemorySopStore(default_sops())
    schema_catalog = schema_catalog or MemorySchemaCatalog(default_schema_domains())
    sql_executor = sql_executor or MysqlReadonlyExecutor(
        host=__import__("os").getenv("SQL_READONLY_HOST", "127.0.0.1"),
        port=int(__import__("os").getenv("SQL_READONLY_PORT", "3306")),
        user=__import__("os").getenv("SQL_READONLY_USER", ""),
        password=__import__("os").getenv("SQL_READONLY_PASSWORD", ""),
        database=__import__("os").getenv("SQL_READONLY_DB", "enterprise_agent"),
    )
    chat_retriever = IngestionRetriever(retriever)
    context_builder = ContextBuilder(max_chunks=settings.top_k)
    return ChatService(
        router=RuleIntentRouter(), conversation=conversation,
        rag=RagAnswerer(chat_retriever, llm, context_builder),
        sop=SopService(sop_store, llm, chat_retriever, context_builder=context_builder),
        nl2sql=Nl2SqlService(llm, schema_catalog, sql_executor),
    )
