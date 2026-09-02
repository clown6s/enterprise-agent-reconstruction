"""语义意图分类器：只做分类，不执行工具、不改权限、不决定 SQL/SOP。"""
import json

from ..domain.models import ChatMessage, Intent, IntentDecision
from .ports import IntentClassifier, LLM

_ALLOWED = {
    "knowledge_qa": Intent.KNOWLEDGE_QA,
    "sop": Intent.SOP,
    "nl2sql": Intent.NL2SQL,
    "mixed": Intent.MIXED,
    "clarification": Intent.CLARIFICATION,
    "chitchat": Intent.CHITCHAT,
}


class SemanticIntentClassifier(IntentClassifier):
    """基于注入 LLM 的语义分类，解析失败或非法一律回退 clarification。"""

    def __init__(self, llm: LLM, *, min_confidence: float = 0.6,
                 max_input: int = 4000):
        self._llm = llm
        self.min_confidence = min_confidence
        self.max_input = max_input

    def classify(self, query: str,
                 history: list[ChatMessage] | None = None) -> IntentDecision:
        if not isinstance(query, str) or not query.strip():
            return IntentDecision(Intent.CLARIFICATION, 1.0, "问题为空", needs_clarification=True)
        query = query.strip()[: self.max_input]
        prompt = (
            "你是意图分类器。只判断问题属于哪一类，不回答内容。\n"
            "允许的 intent：knowledge_qa / sop / nl2sql / mixed / clarification / chitchat。\n"
            "只返回 JSON，字段：intent, confidence(0-1), reason。\n"
            "示例问题：\"TF-IDF怎么计算\" 属于 knowledge_qa。\n"
            f"用户问题：{query}\n"
            "返回 JSON："
        )
        messages = [ChatMessage("user", prompt)]
        try:
            raw = self._llm.chat(messages)
        except Exception:
            return IntentDecision(Intent.CLARIFICATION, 0.0,
                                  "语义分类器调用失败", needs_clarification=True)
        parsed = self._parse(raw, query)
        if parsed is None:
            return IntentDecision(Intent.CLARIFICATION, 0.0,
                                  "语义分类器响应无效", needs_clarification=True)
        return parsed

    def _parse(self, raw: str, query: str) -> IntentDecision | None:
        text = raw.strip()
        if text.startswith("```"):
            text = text.strip("`").strip()
        try:
            data = json.loads(text)
        except (TypeError, ValueError):
            return None
        if not isinstance(data, dict):
            return None
        intent = data.get("intent")
        if intent not in _ALLOWED:
            return None
        try:
            confidence = float(data.get("confidence", 0))
        except (TypeError, ValueError):
            return None
        if not 0 <= confidence <= 1:
            return None
        reason = str(data.get("reason", ""))[:300]
        decision = _ALLOWED[intent]
        return IntentDecision(
            decision, confidence, reason or "语义分类",
            needs_clarification=(decision == Intent.CLARIFICATION))
