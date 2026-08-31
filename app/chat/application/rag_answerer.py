"""RAG execution: retrieve -> bounded context -> LLM -> citations."""
from ..domain.models import ChatMessage, ChatResult, ChatStatus, Citation, Intent
from ..domain.exceptions import LlmError
from ..security.context_boundary import build_messages, sanitize_answer
from .context import RequestContext
from .context_builder import ContextBuilder
from .ports import DocumentRetriever, LLM


class RagAnswerer:
    def __init__(self, retriever: DocumentRetriever, llm: LLM,
                 context_builder: ContextBuilder | None = None):
        self.retriever = retriever
        self.llm = llm
        self.context_builder = context_builder or ContextBuilder()

    def answer(self, query: str, conversation_id: str,
               history: list[ChatMessage] | None = None,
               context: RequestContext | None = None) -> ChatResult:
        context = context or RequestContext()
        items = self.retriever.retrieve(query, top_k=self.context_builder.max_chunks)
        context_text, citations = self.context_builder.build(items)
        if not citations:
            return ChatResult(
                answer="参考资料中没有相关内容，无法回答。",
                status=ChatStatus.NO_CONTEXT, mode=Intent.KNOWLEDGE_QA,
                conversation_id=conversation_id,
                warnings=("no_context",),
                trace_id=context.trace_id,
            )
        messages = build_messages(history or [], query, context_text)
        try:
            raw = self.llm.chat(messages)
        except Exception as exc:
            raise LlmError(f"LLM 回答失败: {type(exc).__name__}") from exc
        answer, warnings = sanitize_answer(raw, citations)
        return ChatResult(
            answer=answer, status=ChatStatus.ANSWERED, mode=Intent.KNOWLEDGE_QA,
            conversation_id=conversation_id, citations=citations, warnings=warnings,
            trace_id=context.trace_id,
        )
