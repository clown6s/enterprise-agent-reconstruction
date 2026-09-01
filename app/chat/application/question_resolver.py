"""Follow-up resolution: anaphora/ellipsis into self-contained questions.

Rule-first and explainable; an optional LLM backend resolves only cases the rules
cannot. The resolved question remains plain text (a data value), never an instruction.
"""
from ..domain.models import ChatMessage, Intent, ResolvedQuestion, SessionState

_CONTINUE_MARKERS = (
    "那", "那么", "继续", "然后", "再", "还有", "接下来", "下一步",
    "其中的", "其中", "只", "都", "呢",
)
_REFERENCE_MARKERS = ("它", "这个", "那个", "这些", "那些", "上述", "刚才")
_EXCLUDE_MARKERS = ("那家", "那个公司", "那么远")


class QuestionResolver:
    def __init__(self, llm=None):
        self._llm = llm  # optional fallback backend exposing .chat(messages)->str

    def resolve(self, question: str, history: list[ChatMessage] | None,
                state: SessionState | None) -> ResolvedQuestion:
        if not isinstance(question, str) or not question.strip():
            return ResolvedQuestion(question="", needs_clarification=True,
                                    reason="问题为空")
        question = question.strip()
        prev = self._last_user_question(history)
        if state is None or state.last_intent is None:
            return ResolvedQuestion(question=question, reason="无会话上下文")

        # Pure continuation cues with no new content.
        if self._is_pure_continuation(question) or self._is_comparison_query(question):
            if state.current_sop_id:
                return ResolvedQuestion(
                    question=question, intent_hint=Intent.SOP,
                    reason="SOP 续走")
            if state.last_intent == Intent.NL2SQL and state.last_domain:
                return ResolvedQuestion(
                    question=question, intent_hint=Intent.NL2SQL,
                    reason="NL2SQL 续查")
            return ResolvedQuestion(question=question,
                                    intent_hint=state.last_intent,
                                    reason="延续上轮意图")

        # Reference/ellipsis: prefix last subject when question is referential.
        if (prev and (any(m in question for m in _REFERENCE_MARKERS)
                      or question.startswith("和") or question.startswith("跟"))):
            if not any(m in question for m in _EXCLUDE_MARKERS):
                merged = self._merge(prev, question)
                if merged != question:
                    return ResolvedQuestion(
                        question=merged, intent_hint=state.last_intent,
                        reason="指代消解补全")

        return ResolvedQuestion(question=question, reason="无改写")

    @staticmethod
    def _last_user_question(history: list[ChatMessage] | None) -> str | None:
        if not history:
            return None
        for m in reversed(history):
            if m.role == "user":
                return m.content
        return None

    @staticmethod
    def _is_pure_continuation(question: str) -> bool:
        return bool(question in {"那下一步呢", "那然后呢", "继续", "下一步呢", "那呢", "然后呢"})

    @staticmethod
    def _is_comparison_query(question: str) -> bool:
        return ("比" in question and "和" in question) or question.endswith("比呢")

    @staticmethod
    def _merge(prev: str, cur: str) -> str:
        # "它/和X" -> 上轮主语(去掉疑问词后)+ 当前补充
        base = prev.rstrip("呢").strip()
        if base.startswith("和") or base.startswith("跟"):
            base = base[1:]
        if cur.startswith("和") or cur.startswith("跟"):
            fragment = cur[1:].lstrip()
            return f"{base} 与 {fragment}"
        return f"{base} {'，'.join(cur.split())}"