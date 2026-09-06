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
    ("怎么做日志脱敏来保护隐私", Intent.KNOWLEDGE_QA),
    ("气道对各种刺激特别敏感，这是哮喘的什么基本特征", Intent.KNOWLEDGE_QA),
    ("大模型Agent先思考、执行、观察结果再继续思考，这个反复循环的过程叫什么？", Intent.KNOWLEDGE_QA),
    ("给Agent接上搜索、执行代码、读写文件这些外部能力，这些能力统称什么", Intent.KNOWLEDGE_QA),
])
def test_routes_natural_language_expressions(query, expected):
    assert RuleIntentRouter().route(query).intent == expected


@pytest.mark.parametrize("query", [
    # 通用/技术知识问题，即使含“统计、多少、数据”等泛化词，也不得进入 NL2SQL。
    "同一个词苹果，一会儿指手机公司，一会儿指水果，如果给每个词只存一个固定向量就分不清了，靠什么机制让它在不同句子里有不同的表示？",
    "统计和普查有什么区别",
    "平均值是什么意思",
    "数据结构是什么",
    "上下文向量和固定词向量有什么区别",
])
def test_general_knowledge_never_routes_to_nl2sql(query):
    assert RuleIntentRouter().route(query).intent == Intent.KNOWLEDGE_QA


@pytest.mark.parametrize("query", [
    "统计本月订单总金额",
    "查询采购申请金额",
    "列出去年销售明细",
])
def test_business_data_questions_still_route_to_nl2sql(query):
    assert RuleIntentRouter().route(query).intent == Intent.NL2SQL
