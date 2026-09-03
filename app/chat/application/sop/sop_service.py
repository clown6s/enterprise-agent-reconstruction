"""SOP 查询与执行编排：衔接 SOP 存储、状态机与 LLM 渲染。"""
from contextlib import nullcontext

from ...domain.exceptions import SopError
from ...domain.models import ChatMessage, ChatResult, ChatStatus, Citation, Intent
from ...security.context_boundary import build_messages, sanitize_answer
from ..context import RequestContext
from ..context_builder import ContextBuilder
from ..ports import LLM, SopStore
from .sop_engine import SopEngine


class SopService:
    def __init__(self, store: SopStore, llm: LLM,
                 engine: SopEngine | None = None,
                 context_builder: ContextBuilder | None = None,
                 trace_provider=None):
        # 必需依赖在构造阶段校验，避免错误延迟到请求期间才暴露为 NoneType 类异常。
        for name, value, methods in (
            ("store", store, ("find", "search", "get_state", "save_state")),
            ("llm", llm, ("chat",)),
        ):
            if value is None:
                raise TypeError(f"SopService 的 {name} 不能为空")
            missing = [m for m in methods if not callable(getattr(value, m, None))]
            if missing:
                raise TypeError(f"SopService 的 {name} 缺少可调用方法: {', '.join(missing)}")
        self.store = store
        self.llm = llm
        self.engine = engine or SopEngine()
        self.context_builder = context_builder or ContextBuilder()
        self.trace_provider = trace_provider

    def _span(self, name: str, **attributes):
        provider = getattr(self.trace_provider, "span", None)
        if not callable(provider):
            return nullcontext()
        return provider(name, **attributes)

    def handle(self, query: str, conversation_id: str,
               history: list[ChatMessage] | None = None,
               *, confirmed: bool = False,
               context: RequestContext | None = None,
               continue_state: bool = True) -> ChatResult:
        context = context or RequestContext()
        # 只有明确续问时才读取旧 SOP 状态；换题不能无条件推进旧流程。
        state = (self.store.get_state(conversation_id, context=context)
                 if continue_state else None)
        if state is not None:
            definition = self.store.find(state.sop_id, state.version, context=context)
            if definition is not None:
                return self._advance(definition, state, conversation_id, confirmed=confirmed, context=context)

        # 结构化 SOP 定义只来自 store；文档检索不产生 SOP 定义。
        definitions = self.store.search(query, context=context)
        definition = definitions[0] if definitions else None
        if definition is None:
            return ChatResult(
                answer="未找到相关 SOP，请提供更具体的流程或步骤关键词。",
                status=ChatStatus.NO_CONTEXT, mode=Intent.SOP,
                conversation_id=conversation_id, warnings=("no_sop",),
            )
        state = self.engine.begin(definition)
        self.store.save_state(conversation_id, state, context=context)
        step = self.engine.current(definition, state)
        return self._render_step(definition, step, state, conversation_id,
                                 high_risk=self.engine.is_high_risk(step), context=context)

    def _advance(self, definition, state, conversation_id, *, confirmed,
                 context: RequestContext | None = None) -> ChatResult:
        context = context or RequestContext()
        step = self.engine.current(definition, state)
        if step.requires_confirmation and not confirmed:
            # 未确认时落库为等待确认状态，避免重启/多实例后丢失该状态。
            waiting_state = self.engine.advance(definition, state, confirmed=False)
            self.store.save_state(conversation_id, waiting_state, context=context)
            return self._render_step(definition, step, waiting_state, conversation_id,
                                     high_risk=True, awaiting=True, context=context)
        next_state = self.engine.advance(definition, state, confirmed=confirmed)
        self.store.save_state(conversation_id, next_state, context=context)
        if next_state.current_step_id == state.current_step_id and not step.next_steps:
            return ChatResult(
                answer=f"SOP《{definition.title}》流程已完成。",
                status=ChatStatus.ANSWERED, mode=Intent.SOP,
                conversation_id=conversation_id,
                sop={"sop_id": definition.sop_id, "version": definition.version,
                     "current_step": step.step_id, "completed": True},
                trace_id=context.trace_id,
            )
        next_step = self.engine.current(definition, next_state)
        return self._render_step(definition, next_step, next_state, conversation_id, context=context)

    def _render_step(self, definition, step, state, conversation_id, *,
                     high_risk=False, awaiting=False,
                     context: RequestContext | None = None) -> ChatResult:
        context = context or RequestContext()
        citation = Citation(source_type="sop", source_id=f"{definition.sop_id}:{step.step_id}",
                            title=definition.title, version=definition.version,
                            step_id=step.step_id)
        content = (f"SOP：{definition.title} v{definition.version}\n"
                   f"当前步骤：{step.instruction}\n")
        if step.preconditions:
            content += "前置条件：" + "；".join(step.preconditions) + "\n"
        if step.inputs:
            content += "需要输入：" + "；".join(step.inputs) + "\n"
        messages = build_messages([], f"请基于 SOP 说明当前步骤和所需操作", content)
        try:
            with self._span("sop.llm_explain"):
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
            warnings=warnings, trace_id=context.trace_id,
        )
