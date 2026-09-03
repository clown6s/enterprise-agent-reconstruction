"""脱离数据库运行的内存会话状态存储，用于测试。"""
from dataclasses import replace
import threading

from ..application.context import identity
from ..application.ports import SessionStateStore
from ..domain.models import SessionState


class MemorySessionStateStore(SessionStateStore):
    def __init__(self):
        self._lock = threading.Lock()
        self._store: dict[tuple, SessionState] = {}

    def _key(self, conversation_id, context):
        tenant, user = identity(context)
        return (tenant, user, conversation_id)

    def get(self, conversation_id: str, *, context) -> SessionState | None:
        with self._lock:
            s = self._store.get(self._key(conversation_id, context))
            return replace(s, version_no=s.version_no + 1) if s else None

    def save(self, conversation_id: str, state: SessionState, *, context) -> None:
        with self._lock:
            self._store[self._key(conversation_id, context)] = state

    def close(self) -> None:
        pass