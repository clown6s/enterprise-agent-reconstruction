from app.chat.application.intent_router import RuleIntentRouter
from app.chat.domain.models import Intent


def test_routes_knowledge_qa():
    decision = RuleIntentRouter().route("报销标准是什么")
    assert decision.intent == Intent.KNOWLEDGE_QA


def test_routes_sop():
    decision = RuleIntentRouter().route("报销超过五万怎么审批，下一步怎么做")
    assert decision.intent == Intent.SOP


def test_routes_nl2sql():
    decision = RuleIntentRouter().route("统计本月有多少笔采购申请超过十万")
    assert decision.intent == Intent.NL2SQL


def test_conflict_becomes_mixed():
    decision = RuleIntentRouter().route("采购超十万怎么审批，上个月有几单")
    assert decision.intent == Intent.MIXED


def test_empty_is_clarification():
    decision = RuleIntentRouter().route("  ")
    assert decision.intent == Intent.CLARIFICATION
