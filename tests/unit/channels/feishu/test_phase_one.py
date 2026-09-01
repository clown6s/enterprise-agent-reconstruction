"""阶段一飞书渠道离线测试。"""
import json
import time

from app.channels.feishu.config import FeishuSettings
from app.channels.feishu.events import parse_text_event
from app.channels.feishu.channel import FeishuChannel
from app.auth.domain.models import Principal


def _event(message_id="m1", text="你好", event_id="e1"):
    return {
        "event_id": event_id,
        "message": {
            "message_id": message_id, "chat_id": "c1", "chat_type": "p2p",
            "message_type": "text", "content": json.dumps({"text": text}),
        },
        "sender": {"sender_id": {"open_id": "ou_1"}},
    }


def test_parse_text_event():
    event = parse_text_event(_event())
    assert event.message_id == "m1"
    assert event.open_id == "ou_1"
    assert event.text == "你好"


def test_parse_unsupported_event_returns_none():
    value = _event()
    value["message"]["message_type"] = "image"
    assert parse_text_event(value) is None


class _Client:
    def __init__(self): self.replies = []
    def reply_text(self, message_id, text): self.replies.append((message_id, text)); return True
    def close(self): pass


class _Identity:
    def resolve(self, **kwargs):
        return Principal("tenant-test", "user-test-001", "test_user",
                         permissions=("chat:ask",))


class _Idempotency:
    def __init__(self): self.claims = []; self.marks = []
    def claim(self, **kwargs):
        self.claims.append(kwargs); return True
    def mark(self, **kwargs): self.marks.append(kwargs)


class _Chat:
    def __init__(self): self.calls = []
    def ask(self, text, **kwargs):
        self.calls.append((text, kwargs))
        return type("Result", (), {"answer": "回答"})()


def test_channel_processes_text_once():
    client, idem, chat = _Client(), _Idempotency(), _Chat()
    channel = FeishuChannel(
        settings=FeishuSettings(enabled=True, app_id="a", app_secret="s", tenant_id="tenant-test"),
        chat_service=chat, client=client, identity=_Identity(), idempotency=idem,
    )
    channel._on_message(_event())
    channel._work_loop_once = None
    # Process the queued work synchronously to make the test deterministic.
    item = channel._queue.get_nowait()
    channel._handle(item.event)
    assert client.replies == [("m1", "回答")]
    assert chat.calls[0][1]["context"].user_id == "user-test-001"
    assert chat.calls[0][1]["conversation_id"] == "feishu:tenant-test:c1"


def test_channel_deduplicates_event():
    client, idem, chat = _Client(), _Idempotency(), _Chat()
    idem.claim = lambda **kwargs: False
    channel = FeishuChannel(
        settings=FeishuSettings(enabled=True, app_id="a", app_secret="s", tenant_id="tenant-test"),
        chat_service=chat, client=client, identity=_Identity(), idempotency=idem,
    )
    channel._on_message(_event())
    assert channel._queue.empty()
