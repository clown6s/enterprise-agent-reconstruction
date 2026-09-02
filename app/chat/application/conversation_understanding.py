"""多轮会话关系理解：追问、换题、混合和澄清。

本模块只负责理解问题和生成独立问题，不执行检索、SQL 或 SOP 动作。
"""
import json
import re

from ..domain.models import ConversationRelation, Intent, ResolvedQuestion, SessionState


class RuleConversationUnderstanding:
    """规则优先的关系理解器，可选注入 LLM 处理长尾表达。"""

    def __init__(self, llm=None, *, max_history: int = 6, min_confidence: float = 0.7):
        self.llm = llm
        self.max_history = max(1, min(max_history, 20))
        self.min_confidence = min_confidence

    def understand(self, question: str, history: list | None,
                   state: SessionState | None) -> ResolvedQuestion:
        question = (question or "").strip()
        if not question:
            return ResolvedQuestion(
                question="", relation=ConversationRelation.CLARIFICATION,
                needs_clarification=True, confidence=1.0, reason="问题为空")
        recent = (history or [])[-self.max_history:]
        previous = self._last_user_question(recent)

        mixed = self._split_mixed(question)
        if mixed:
            return ResolvedQuestion(
                question=question, relation=ConversationRelation.MIXED,
                subtasks=tuple(mixed), confidence=0.9, reason="检测到多个独立任务")

        if state is None or state.last_intent is None or previous is None:
            return ResolvedQuestion(
                question=question, relation=ConversationRelation.NEW_TOPIC,
                topic=self._topic_hint(question), confidence=0.95,
                reason="无可用历史主题")

        if self._is_explicit_new_topic(question, previous):
            return ResolvedQuestion(
                question=question, relation=ConversationRelation.NEW_TOPIC,
                topic=self._topic_hint(question), confidence=0.9,
                reason="当前问题自洽且出现新主题")

        if self._is_follow_up(question):
            rewritten = self._rewrite_follow_up(question, previous, state)
            return ResolvedQuestion(
                question=rewritten, relation=ConversationRelation.FOLLOW_UP,
                intent_hint=state.last_intent, topic=state.extra.get("topic"),
                confidence=0.9, referenced_turns=(len(recent),), reason="明确续问")

        if self._needs_llm(question):
            result = self._llm_understand(question, recent, state)
            if result is not None:
                return result

        # 默认把有完整主语/对象的问题视为新主题，宁可不继承也不串台。
        return ResolvedQuestion(
            question=question, relation=ConversationRelation.NEW_TOPIC,
            topic=self._topic_hint(question), confidence=0.75,
            reason="默认按独立新问题处理")

    @staticmethod
    def _last_user_question(history):
        for item in reversed(history):
            if getattr(item, "role", None) == "user":
                return item.content
        return None

    @staticmethod
    def _is_follow_up(question: str) -> bool:
        if question in {"那呢", "然后呢", "继续", "下一步呢", "那下一步呢", "其中呢"}:
            return True
        return (question.startswith(("和", "跟", "其中", "只看", "还有"))
                or bool(re.search(r"^(它|上述|刚才提到的)(?!是.{1,12}(?:矛盾|机制|问题))", question)))

    @staticmethod
    def _is_explicit_new_topic(question: str, previous: str) -> bool:
        # “这个/那个 + 明确名词”通常是当前句内指示，不应强接上一轮。
        if re.search(r"^(这个|那个|这些|那些).{2,}(矛盾|机制|问题|方案|概念|特征|过程)", question):
            return True
        # 有明确新对象且不是代词开头，默认切换主题。
        if not question.startswith(("它", "上述", "刚才", "其中", "和", "跟", "那", "然后")):
            return len(question) >= 6 and not any(x in question for x in ("下一步", "其中", "和上月"))
        return False

    @staticmethod
    def _rewrite_follow_up(question: str, previous: str, state: SessionState) -> str:
        subject = state.extra.get("topic") if state.extra else None
        subject = subject or previous.rstrip("？?。 ")
        if question.startswith(("和", "跟")):
            return f"{subject} 与 {question[1:].lstrip()}"
        if question.startswith("其中") and state.last_domain:
            return f"{state.last_domain} {question}"
        return f"{subject} {question}"

    @staticmethod
    def _topic_hint(question: str) -> str | None:
        # 保留短主题摘要，绝不作为权限依据。
        value = re.sub(r"[，。！？!?、：:（）()\"“”]", " ", question)
        return " ".join(value.split())[:120] or None

    @staticmethod
    def _split_mixed(question: str) -> list[dict] | None:
        if not re.search(r"并且|同时|以及|另外|还要|并告诉", question):
            return None
        parts = re.split(r"(?:并且|同时|以及|另外|还要|并告诉)", question, maxsplit=1)
        if len(parts) != 2 or not all(part.strip() for part in parts):
            return None
        return [{"question": part.strip(), "intent": None} for part in parts]

    @staticmethod
    def _needs_llm(question: str) -> bool:
        return len(question) >= 8 and not any(
            marker in question for marker in ("是什么", "叫什么", "统计", "多少", "流程", "下一步"))

    def _llm_understand(self, question, history, state):
        if self.llm is None:
            return None
        from .ports import LLM
        from ..domain.models import ChatMessage
        prompt = ("只做会话关系判断，不回答问题。返回 JSON：relation 必须为 "
                  "follow_up/new_topic/mixed/clarification；rewritten_question、topic、"
                  "intent_hint、confidence、referenced_turns、subtasks。不要调用工具。\n"
                  f"上一轮：{self._last_user_question(history) or ''}\n当前：{question}")
        try:
            raw = self.llm.chat([ChatMessage("user", prompt)])
            data = json.loads(raw.strip().strip("`"))
            relation = ConversationRelation(data["relation"])
            confidence = float(data.get("confidence", 0))
            if confidence < self.min_confidence:
                return None
            hint = data.get("intent_hint")
            intent = Intent(hint) if hint else None
            subtasks = tuple(data.get("subtasks") or ())
            return ResolvedQuestion(
                question=str(data.get("rewritten_question") or question)[:12000],
                relation=relation, topic=data.get("topic"), intent_hint=intent,
                confidence=confidence, referenced_turns=tuple(data.get("referenced_turns") or ()),
                subtasks=subtasks, needs_clarification=relation == ConversationRelation.CLARIFICATION,
                reason="LLM 会话关系判断")
        except (TypeError, ValueError, KeyError, json.JSONDecodeError):
            return None
