"""多轮关系理解测试：换题隔离、追问改写和混合拆分。"""
from app.chat.application.conversation_understanding import RuleConversationUnderstanding
from app.chat.domain.models import (
    ChatMessage, ConversationRelation, Intent, SessionState,
)


def _state(intent=Intent.KNOWLEDGE_QA, **extra):
    return SessionState(last_intent=intent, extra=extra)


def test_new_topic_does_not_merge_internal_this_phrase():
    engine = RuleConversationUnderstanding()
    result = engine.understand(
        "这个又想压缩又怕破坏缓存的矛盾怎么理解？",
        [ChatMessage("user", "苹果在不同句子里为什么有不同表示？")],
        _state(extra={"topic": "苹果向量"}),
    )
    assert result.relation == ConversationRelation.NEW_TOPIC
    assert "苹果" not in result.question


def test_follow_up_rewrites_anaphora_with_topic():
    engine = RuleConversationUnderstanding()
    result = engine.understand(
        "它和 function calling 有什么区别？",
        [ChatMessage("user", "MCP 是什么？")],
        _state(extra={"topic": "MCP"}),
    )
    assert result.relation == ConversationRelation.FOLLOW_UP
    assert "MCP" in result.question
    assert result.intent_hint == Intent.KNOWLEDGE_QA


def test_mixed_question_returns_independent_subtasks():
    engine = RuleConversationUnderstanding()
    result = engine.understand(
        "统计本月采购金额，并告诉我审批流程",
        [], None,
    )
    assert result.relation == ConversationRelation.MIXED
    assert len(result.subtasks) == 2


def test_unknown_long_question_defaults_to_new_topic_without_history_merge():
    engine = RuleConversationUnderstanding()
    result = engine.understand(
        "请解释上下文压缩和缓存失效之间的工程权衡",
        [ChatMessage("user", "MCP 是什么？")],
        _state(extra={"topic": "MCP"}),
    )
    assert result.relation == ConversationRelation.NEW_TOPIC
    assert "MCP" not in result.question
