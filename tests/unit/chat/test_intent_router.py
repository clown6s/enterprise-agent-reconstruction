import pytest

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


@pytest.mark.parametrize("query,expected", [
    ("帮我看看最近采购花了多少钱", Intent.NL2SQL),
    ("RAG 技术是做什么的", Intent.KNOWLEDGE_QA),
    ("入职流程怎么办理", Intent.SOP),
    ("去年订单总金额是多少", Intent.NL2SQL),
    ("怎么做采购申请的审批", Intent.SOP),
    ("这个月销售额排名", Intent.NL2SQL),
    ("报销标准是什么", Intent.KNOWLEDGE_QA),
    ("给Agent接上搜索、执行代码、读写文件这些外部能力，这些能力统称什么", Intent.KNOWLEDGE_QA),
])
def test_routes_natural_language_expressions(query, expected):
    assert RuleIntentRouter().route(query).intent == expected
