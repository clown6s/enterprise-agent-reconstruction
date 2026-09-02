"""Chat composition root: concrete adapters are wired here only."""
import os

from .config import read_settings, read_storage_settings
from .defaults import default_schema_domains, default_sops
from ..adapters.ingestion_retriever import IngestionRetriever
from ..adapters.memory_conversation_store import MemoryConversationStore
from ..adapters.memory_schema_catalog import MemorySchemaCatalog
from ..adapters.memory_sop_store import MemorySopStore
from ..adapters.memory_session_state_store import MemorySessionStateStore
from ..adapters.mysql_conversation_store import MysqlConversationStore
from ..adapters.mysql_pool import MysqlPool
from ..adapters.mysql_schema_catalog import MysqlSchemaCatalog
from ..adapters.mysql_session_state_store import MysqlSessionStateStore
from ..adapters.mysql_sop_store import MysqlSopStore
from ..adapters.mysql_audit_logger import MysqlAuditLogger
from ..adapters.mysql_readonly_executor import MysqlReadonlyExecutor
from ..adapters.openai_compat_chat import OpenAiCompatChat
from ..application.chat_service import ChatService
from ..application.schema_registry import SchemaRegistry
from ..application.schema_admin import SchemaAdminService
from ..adapters.mysql_schema_registry import MysqlSchemaRegistry
from ..application.context_builder import ContextBuilder
from ..application.conversation_understanding import RuleConversationUnderstanding
from ..application.intent_router import HybridIntentRouter, RuleIntentRouter
from ..application.semantic_intent_classifier import SemanticIntentClassifier
from ..application.nl2sql.nl2sql_service import Nl2SqlService
from ..application.question_resolver import QuestionResolver
from ..application.rag_answerer import RagAnswerer
from ..application.sop.sop_service import SopService
from app.observability.trace_provider import OtelTraceProvider


def build_schema_admin():
    """Build the isolated schema administration service without chat/LLM setup."""
    storage = read_storage_settings()
    if storage.backend != "mysql":
        raise RuntimeError("Schema Registry 管理接口需要 MySQL 存储")
    pool = MysqlPool(
        host=storage.mysql_host, port=storage.mysql_port,
        user=storage.mysql_user, password=storage.mysql_password,
        database=storage.mysql_database,
    )
    return SchemaAdminService(SchemaRegistry(MysqlSchemaRegistry(pool)))


def build_chat(*, retriever, llm=None, conversation=None,
               sop_store=None, schema_catalog=None, sql_executor=None,
               audit=None, session_state=None, question_resolver=None) -> ChatService:
    settings = read_settings()
    storage = read_storage_settings()
    llm = llm or OpenAiCompatChat(
        settings.api_key, base_url=settings.base_url, model=settings.model,
        temperature=settings.temperature, max_tokens=settings.max_tokens,
        timeout=settings.llm_timeout, max_retries=settings.llm_max_retries,
    )
    if conversation is None or sop_store is None or schema_catalog is None:
        if storage.backend == "mysql":
            pool = MysqlPool(
                host=storage.mysql_host, port=storage.mysql_port,
                user=storage.mysql_user, password=storage.mysql_password,
                database=storage.mysql_database,
            )
            conversation = conversation or MysqlConversationStore(pool)
            sop_store = sop_store or MysqlSopStore(pool)
            schema_catalog = schema_catalog or MysqlSchemaCatalog(pool)
            if session_state is None:
                session_state = MysqlSessionStateStore(pool)
            if audit is None:
                audit = MysqlAuditLogger(pool)
        else:
            conversation = conversation or MemoryConversationStore()
            sop_store = sop_store or MemorySopStore(default_sops())
            schema_catalog = schema_catalog or MemorySchemaCatalog(default_schema_domains())
            if session_state is None:
                session_state = MemorySessionStateStore()
    sql_executor = sql_executor or MysqlReadonlyExecutor(
        host=os.getenv("SQL_READONLY_HOST", "127.0.0.1"),
        port=int(os.getenv("SQL_READONLY_PORT", "3306")),
        user=os.getenv("SQL_READONLY_USER", ""),
        password=os.getenv("SQL_READONLY_PASSWORD", ""),
        database=os.getenv("SQL_READONLY_DB", "enterprise_agent"),
    )
    chat_retriever = IngestionRetriever(retriever)
    context_builder = ContextBuilder(max_chunks=settings.top_k)
    trace_provider = OtelTraceProvider()
    classifier = SemanticIntentClassifier(llm)
    router = HybridIntentRouter(RuleIntentRouter(), classifier)
    return ChatService(
        router=router, conversation=conversation,
        rag=RagAnswerer(chat_retriever, llm, context_builder, trace_provider),
        sop=SopService(sop_store, llm, chat_retriever,
                      context_builder=context_builder, trace_provider=trace_provider),
        nl2sql=Nl2SqlService(llm, schema_catalog, sql_executor,
                             trace_provider=trace_provider),
        audit=audit,
        session_state=session_state,
        question_resolver=question_resolver,
        understanding=RuleConversationUnderstanding(llm),
    )
