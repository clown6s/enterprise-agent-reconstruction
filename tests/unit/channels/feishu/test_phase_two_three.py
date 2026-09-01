"""阶段二/三卡片、群聊和确认动作的离线测试。"""
import json

from app.channels.feishu.cards import FeishuCardRenderer
from app.channels.feishu.events import parse_text_event
from app.chat.domain.models import ChatResult, ChatStatus, Citation, CitationAudit, Intent


def test_card_renderer_includes_sop_confirmation_only_for_high_risk():
    result = ChatResult(
        answer="请确认", status=ChatStatus.ANSWERED, mode=Intent.SOP,
        conversation_id="c", sop={"sop_id": "s", "version": "v1",
                                  "current_step": "s3", "high_risk": True},
    )
    card = FeishuCardRenderer().render(result, action_id="a1")
    assert "sop_confirm" in card
    assert "a1" in card


def test_card_renderer_contains_no_identity_fields():
    result = ChatResult("答案", ChatStatus.ANSWERED, Intent.KNOWLEDGE_QA, "c",
                        citations=(Citation("document", "d"),))
    card = FeishuCardRenderer().render(result)
    assert "tenant_id" not in card and "user_id" not in card


def test_group_message_requires_mention_marker():
    event = {
        "event_id": "e", "message": {
            "message_id": "m", "chat_id": "c", "chat_type": "group",
            "message_type": "text", "mentions": [{"id": {"open_id": "ou_bot"}}],
            "content": json.dumps({"text": "@机器人 RAG 是什么"}),
        }, "sender": {"sender_id": {"open_id": "ou_user"}},
    }
    parsed = parse_text_event(event)
    assert parsed.mentioned is True and parsed.chat_type == "group"
