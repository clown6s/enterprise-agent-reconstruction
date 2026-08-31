"""Deterministic intent routing; no infrastructure dependency."""
import re

from ..domain.models import ChatMessage, Intent, IntentDecision


_TERMS = {
    Intent.NL2SQL: (("统计", 3), ("多少", 3), ("总数", 3), ("合计", 3),
                    ("占比", 3), ("平均", 2), ("同比", 3), ("环比", 3),
                    ("排名", 3), ("本月", 2), ("上月", 2), ("上个月", 2),
                    ("最近", 1), ("列出", 2), ("明细", 2), ("金额", 2),
                    ("销售额", 3)),
    Intent.SOP: (("流程", 3), ("步骤", 3), ("怎么操作", 3), ("怎么办", 3),
                 ("下一步", 4), ("接下来", 3), ("审批", 2), ("办理", 2),
                 ("提交", 2), ("需要什么材料", 3), ("已完成", 2), ("卡在", 3)),
    Intent.KNOWLEDGE_QA: (("是什么", 2), ("为什么", 2), ("定义", 2),
                          ("标准", 2), ("规定", 2), ("区别", 2), ("依据", 2),
                          ("说明", 1), ("含义", 2)),
}


class RuleIntentRouter:
    """Routes obvious requests cheaply and asks for clarification on conflicts."""

    def __init__(self, *, min_confidence: float = 0.6, ambiguity_gap: float = 0.15):
        self.min_confidence = min_confidence
        self.ambiguity_gap = ambiguity_gap

    def route(self, query: str, history: list[ChatMessage] | None = None) -> IntentDecision:
        if not isinstance(query, str) or not query.strip():
            return IntentDecision(Intent.CLARIFICATION, 1.0, "问题为空", needs_clarification=True)
        scores = {intent: 0.0 for intent in _TERMS}
        for intent, terms in _TERMS.items():
            scores[intent] = sum(weight for term, weight in terms if term in query)
        ordered = sorted(scores.items(), key=lambda item: item[1], reverse=True)
        top_intent, top_score = ordered[0]
        second_score = ordered[1][1]

        # Explicit numeric/time aggregation is a strong NL2SQL signal.
        if top_score and (re.search(r"\d+(?:\.\d+)?\s*(万|元|个|笔|件|天|月|年)", query)
                          or any(term in query for term in ("本月", "上月", "同比", "环比"))):
            if scores[Intent.NL2SQL] >= second_score:
                top_intent = Intent.NL2SQL
                top_score = max(top_score, scores[Intent.NL2SQL] + 1)

        if not top_score:
            previous = self._previous_intent(history)
            if previous is not None and any(word in query for word in ("那", "继续", "下一步", "多少")):
                return IntentDecision(previous, 0.65, "沿用会话意图")
            return IntentDecision(Intent.CLARIFICATION, 0.0, "无明确意图", needs_clarification=True)
        # 同时命中流程(SOP)与数据查询(NL2SQL)信号 → 混合问题，分而治之。
        if scores[Intent.SOP] > 0 and scores[Intent.NL2SQL] > 0:
            return IntentDecision(Intent.MIXED, 0.5, "同时含流程与数据查询信号")
        total = sum(scores.values())
        confidence = top_score / total if total else 0.0
        if second_score and (top_score - second_score) / top_score < self.ambiguity_gap:
            return IntentDecision(Intent.MIXED, confidence, "多个意图信号冲突")
        if confidence < self.min_confidence:
            return IntentDecision(Intent.CLARIFICATION, confidence, "意图置信度不足", needs_clarification=True)
        return IntentDecision(top_intent, confidence, "规则命中")

    @staticmethod
    def _previous_intent(history: list[ChatMessage] | None) -> Intent | None:
        if not history:
            return None
        for message in reversed(history):
            if message.role == "assistant":
                for intent in Intent:
                    if f"mode={intent.value}" in message.content:
                        return intent
        return None
