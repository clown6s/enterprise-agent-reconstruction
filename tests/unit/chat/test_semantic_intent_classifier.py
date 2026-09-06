import json

from app.chat.application.intent_router import HybridIntentRouter, RuleIntentRouter
from app.chat.application.semantic_intent_classifier import SemanticIntentClassifier
from app.chat.domain.models import Intent


class FakeLLM:
    def __init__(self, response):
        self.response = response
        self.calls = 0

    def chat(self, messages):
        self.calls += 1
        return self.response


def test_semantic_classifier_routes_tfidf_question():
    llm = FakeLLM(json.dumps({
        "intent": "knowledge_qa", "confidence": 0.96,
        "reason": "询问算法定义",
    }))
    result = SemanticIntentClassifier(llm).classify(
        "一个词在文章里出现得多、在全部文档里出现得少，按词频和稀有度打分的算法是什么")
    assert result.intent == Intent.KNOWLEDGE_QA
    assert llm.calls == 1


def test_hybrid_skips_llm_for_high_confidence_rule():
    llm = FakeLLM('{"intent":"nl2sql","confidence":1}')
    router = HybridIntentRouter(RuleIntentRouter(), SemanticIntentClassifier(llm))
    assert router.route("统计本月订单总金额").intent == Intent.NL2SQL
    assert llm.calls == 0


def test_hybrid_uses_llm_for_no_rule_match():
    llm = FakeLLM('{"intent":"knowledge_qa","confidence":0.95,"reason":"概念解释"}')
    router = HybridIntentRouter(RuleIntentRouter(), SemanticIntentClassifier(llm))
    assert router.route("随便聊聊吧").intent == Intent.KNOWLEDGE_QA
    assert llm.calls == 1


def test_semantic_invalid_json_is_clarification():
    llm = FakeLLM("不是 JSON")
    result = SemanticIntentClassifier(llm).classify("请解释倒排索引如何帮助检索")
    assert result.intent == Intent.CLARIFICATION
    assert result.needs_clarification is True


def test_semantic_unknown_intent_is_clarification():
    llm = FakeLLM('{"intent":"delete_data","confidence":1}')
    result = SemanticIntentClassifier(llm).classify("请解释倒排索引")
    assert result.intent == Intent.CLARIFICATION
