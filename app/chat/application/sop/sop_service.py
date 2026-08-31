"""SOP query and execution orchestration against the SOP store and engine."""
from ...domain.exceptions import SopError
from ...domain.models import ChatMessage, ChatResult, ChatStatus, Citation, Intent
from ...security.context_boundary import build_messages, sanitize_answer
from ..context_builder import ContextBuilder
from ..ports import DocumentRetriever, LLM, SopStore
from .sop_engine import SopEngine


class SopService:
    def __init__(self, store: SopStore, llm: LLM,
                 retriever: DocumentRetriever | None = None,
                 engine: SopEngine | None = None,
                 context_builder: ContextBuilder | None = None):
        self.store = store
        self.llm = llm
        self.retriever = retriever
        self.engine = engine or SopEngine()
        self.context_builder = context_builder or ContextBuilder()

    def handle(self, query: str, conversation_id: str,
               history: list[ChatMessage] | None = None,
               *, confirmed: bool = False) -> ChatResult:
        # Try to continue an active execution in this conversation.
        state = self.store.get_state(conversation_id)
        if state is not None:
            definition = self.store.find(state.sop_id, state.version)
            if definition is not None:
                return self._advance(definition, state, conversation_id, confirmed=confirmed)

        # Otherwise locate a SOP by structured search first.
        definitions = self.store.search(query)
        definition = definitions[0] if definitions else self._retrieve_sop(query)
        if definition is None:
            return ChatResult(
                answer="未找到相关 SOP，请提供更具体的流程或步骤关键词。",
                status=ChatStatus.NO_CONTEXT, mode=Intent.SOP,
                conversation_id=conversation_id, warnings=("no_sop",),
            )
        state = self.engine.begin(definition)
        self.store.save_state(conversation_id, state)
        step = self.engine.current(definition, state)
        return self._render_step(definition, step, state, conversation_id,
                                 high_risk=self.engine.is_high_risk(step))

    def _advance(self, definition, state, conversation_id, *, confirmed) -> ChatResult:
        step = self.engine.current(definition, state)
        if step.requires_confirmation and not confirmed:
            return self._render_step(definition, step, state, conversation_id,
                                     high_risk=True, awaiting=True)
        next_state = self.engine.advance(definition, state, confirmed=confirmed)
        self.store.save_state(conversation_id, next_state)
        if next_state.current_step_id == state.current_step_id and not step.next_steps:
            return ChatResult(
                answer=f"SOP《{definition.title}》流程已完成。",
                status=ChatStatus.ANSWERED, mode=Intent.SOP,
                conversation_id=conversation_id,
                sop={"sop_id": definition.sop_id, "version": definition.version,
                     "current_step": step.step_id, "completed": True},
            )
        next_step = self.engine.current(definition, next_state)
        return self._render_step(definition, next_step, next_state, conversation_id)

    def _retrieve_sop(self, query: str):
        if self.retriever is None:
            return None
        items = self.retriever.retrieve(query, top_k=5)
        return None  # document retrieval only grounds; structured definitions come from store

    def _render_step(self, definition, step, state, conversation_id, *,
                     high_risk=False, awaiting=False) -> ChatResult:
        citation = Citation(source_type="sop", source_id=f"{definition.sop_id}:{step.step_id}",
                            title=definition.title, version=definition.version,
                            step_id=step.step_id)
        context = (f"SOP：{definition.title} v{definition.version}\n"
                   f"当前步骤：{step.instruction}\n")
        if step.preconditions:
            context += "前置条件：" + "；".join(step.preconditions) + "\n"
        if step.inputs:
            context += "需要输入：" + "；".join(step.inputs) + "\n"
        messages = build_messages([], f"请基于 SOP 说明当前步骤和所需操作", context)
        try:
            raw = self.llm.chat(messages)
        except Exception as exc:
            from ...domain.exceptions import LlmError
            raise LlmError(f"LLM 解释 SOP 失败: {type(exc).__name__}") from exc
        answer, warnings = sanitize_answer(raw, (citation,))
        if awaiting:
            answer += "\n\n⚠️ 该步骤为高风险操作，请确认后再继续。"
        return ChatResult(
            answer=answer, status=ChatStatus.ANSWERED, mode=Intent.SOP,
            conversation_id=conversation_id, citations=(citation,),
            sop={"sop_id": definition.sop_id, "version": definition.version,
                 "current_step": step.step_id, "awaiting_confirmation": awaiting,
                 "high_risk": high_risk},
            warnings=warnings,
        )
