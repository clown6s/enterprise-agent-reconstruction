"""飞书文本渠道：事件回调只入队，业务处理在有界 worker 中执行。"""
from dataclasses import dataclass
import queue
import threading
import uuid

from app.chat.application.context import RequestContext

from .cards import FeishuCardRenderer
from .config import FeishuSettings
from .events import FeishuTextEvent, parse_text_event
from .ports import FeishuClient, FeishuIdempotencyStore, FeishuIdentityResolver


@dataclass(frozen=True)
class _WorkItem:
    event: FeishuTextEvent


class FeishuChannel:
    """将飞书事件适配为 ChatService.ask 的渠道适配器。"""

    def __init__(self, *, settings: FeishuSettings, chat_service,
                 client: FeishuClient, identity: FeishuIdentityResolver,
                 idempotency: FeishuIdempotencyStore,
                 card_renderer: FeishuCardRenderer | None = None,
                 owned_resources=(), queue_size: int = 100):
        self.settings = settings
        self.chat_service = chat_service
        self.client = client
        self.identity = identity
        self.idempotency = idempotency
        self.card_renderer = card_renderer
        self._owned_resources = tuple(owned_resources)
        self._queue: queue.Queue[_WorkItem | None] = queue.Queue(maxsize=queue_size)
        self._stop = threading.Event()
        self._worker: threading.Thread | None = None
        self._ws = None
        self._started = False

    @property
    def enabled(self) -> bool:
        return self.settings.usable

    def start(self) -> bool:
        if not self.enabled or self._started:
            return False
        self._stop.clear()
        self._worker = threading.Thread(target=self._work_loop,
                                        name="feishu-chat-worker", daemon=True)
        self._worker.start()
        try:
            self._start_websocket()
        except Exception:
            self.stop()
            raise
        self._started = True
        return True

    def _start_websocket(self) -> None:
        try:
            import lark_oapi
            from lark_oapi.api.im.v1.model.p2_im_message_receive_v1 import P2ImMessageReceiveV1
            from lark_oapi.event.dispatcher_handler import EventDispatcherHandler
            from lark_oapi.ws import Client as WsClient
        except ImportError as exc:
            raise RuntimeError("飞书 SDK 未安装") from exc
        dispatcher = (EventDispatcherHandler.builder(
            self.settings.app_id, self.settings.app_secret)
            .register_p2_im_message_receive_v1(self._on_message)
            .register_p2_card_action_trigger(self._on_card_action)
            .build())
        self._ws = WsClient(
            self.settings.app_id, self.settings.app_secret,
            log_level=lark_oapi.LogLevel.ERROR, event_handler=dispatcher,
        )
        thread = threading.Thread(target=self._ws.start,
                                  name="feishu-websocket", daemon=True)
        thread.start()

    def _on_message(self, event) -> None:
        item = parse_text_event(event)
        if item is None:
            return
        if item.chat_type != "p2p" and self.settings.require_mention and not item.mentioned:
            return
        if not self.idempotency.claim(
                tenant_id=self.settings.tenant_id, event_id=item.event_id or item.message_id,
                message_id=item.message_id, event_type="message.receive"):
            return
        try:
            self._queue.put_nowait(_WorkItem(item))
        except queue.Full:
            self._mark(item, "failed", "queue_full")

    def _on_card_action(self, event):
        """快速接收卡片动作；实际确认在后台线程按当前 SOP 状态执行。"""
        action = getattr(event, "action", None)
        if isinstance(event, dict):
            action = event.get("action", event)
        value = action.get("value", {}) if isinstance(action, dict) else getattr(action, "value", {}) or {}
        if isinstance(value, str):
            import json
            try:
                value = json.loads(value)
            except (TypeError, ValueError):
                value = {}
        if not isinstance(value, dict) or value.get("action") != "sop_confirm":
            return
        # 回调身份必须来自事件 sender，不能来自 card value。
        sender = getattr(event, "user", None)
        if isinstance(event, dict):
            sender = event.get("user", event.get("operator", {}))
        open_id = (sender.get("open_id", "") if isinstance(sender, dict)
                   else getattr(sender, "open_id", "") or "")
        principal = self.identity.resolve(
            tenant_id=self.settings.tenant_id, app_id=self.settings.app_id,
            open_id=open_id,
        )
        if principal is None or "sop:execute" not in principal.permissions:
            return
        context = RequestContext(
            trace_id=str(uuid.uuid4()), tenant_id=principal.tenant_id,
            user_id=principal.user_id, roles=principal.roles,
            permissions=principal.permissions, authenticated=True,
            department_ids=principal.department_ids,
        )
        conversation_id = value.get("conversation_id")
        if not conversation_id or not self.settings.allow_sop_action:
            return
        try:
            self.chat_service.ask("确认继续", conversation_id=conversation_id,
                                  confirmed=True, context=context)
        except Exception:
            self._mark(FeishuTextEvent(
                event_id=str(uuid.uuid4()), message_id="", chat_id="",
                chat_type="p2p", open_id=open_id, text="", trace_id=str(uuid.uuid4())),
                "failed", "sop_confirm_failed")

    def _work_loop(self):
        while not self._stop.is_set():
            try:
                item = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue
            if item is None:
                self._queue.task_done()
                break
            try:
                self._handle(item.event)
                self._mark(item.event, "succeeded")
            except Exception:
                self._mark(item.event, "failed", "handler_error")
            finally:
                self._queue.task_done()

    def _handle(self, event: FeishuTextEvent) -> None:
        principal = self.identity.resolve(
            tenant_id=self.settings.tenant_id,
            app_id=self.settings.app_id,
            open_id=event.open_id,
        )
        if principal is None:
            self.client.reply_text(event.message_id, "当前飞书账号尚未绑定企业账号，请联系管理员。")
            return
        context = RequestContext(
            trace_id=event.trace_id or str(uuid.uuid4()),
            tenant_id=principal.tenant_id, user_id=principal.user_id,
            roles=principal.roles, permissions=principal.permissions,
            authenticated=True, department_ids=principal.department_ids,
            expires_at=(principal.expires_at.isoformat() if principal.expires_at else None),
        )
        conversation_id = f"feishu:{principal.tenant_id}:{event.chat_id}"
        result = self.chat_service.ask(
            event.text, conversation_id=conversation_id, context=context,
        )
        if self.card_renderer is not None:
            card = self.card_renderer.render(result)
            if self.client.reply_card(event.message_id, card):
                return
        if not self.client.reply_text(event.message_id, result.answer):
            raise RuntimeError("飞书回复失败")

    def _mark(self, event, status, error_code=None):
        mark = getattr(self.idempotency, "mark", None)
        if callable(mark):
            mark(tenant_id=self.settings.tenant_id,
                 event_id=event.event_id or event.message_id,
                 status=status, error_code=error_code)

    def stop(self) -> None:
        self._stop.set()
        try:
            self._queue.put_nowait(None)
        except queue.Full:
            pass
        if self._worker is not None:
            self._worker.join(timeout=10)
        stop = getattr(self._ws, "stop", None)
        if callable(stop):
            stop()
        self.client.close()
        for resource in self._owned_resources:
            close = getattr(resource, "close", None)
            if callable(close):
                close()
        self._started = False
