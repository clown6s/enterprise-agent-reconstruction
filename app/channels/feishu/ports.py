"""飞书渠道所需端口；具体存储和 SDK 实现在 adapters。"""
from typing import Protocol

from app.auth.domain.models import Principal


class FeishuIdentityResolver(Protocol):
    def resolve(self, *, tenant_id: str, app_id: str, open_id: str) -> Principal | None: ...


class FeishuIdempotencyStore(Protocol):
    def claim(self, *, tenant_id: str, event_id: str, message_id: str,
              event_type: str) -> bool: ...


class FeishuClient(Protocol):
    def reply_text(self, message_id: str, text: str) -> bool: ...
    def reply_card(self, message_id: str, card_json: str) -> bool: ...
    def close(self) -> None: ...


class FeishuDeliveryStore(Protocol):
    def enqueue(self, *, tenant_id: str, idempotency_key: str, event_id: str,
                message_id: str, receive_id: str, receive_id_type: str,
                message_type: str, payload: str) -> None: ...
    def mark(self, *, tenant_id: str, idempotency_key: str, status: str,
             error_code: str | None = None) -> None: ...
