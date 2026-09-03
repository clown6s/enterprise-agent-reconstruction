"""内存会话存储（端口实现，可替换为 MySQL）。"""
from collections import defaultdict, deque
import threading

from ..application.ports import ConversationStore
from ..domain.models import ChatMessage


class MemoryConversationStore(ConversationStore):
    def __init__(self, *, capacity: int = 50):
        self._capacity = capacity
        self._lock = threading.Lock()
        self._store: dict[str, deque] = defaultdict(lambda: deque(maxlen=capacity))

    def get_or_create(self, conversation_id: str, *, context=None) -> None:
        with self._lock:
            self._store.setdefault(conversation_id, deque(maxlen=self._capacity))

    def append(self, conversation_id: str, message: ChatMessage, *, context=None) -> None:
        with self._lock:
            self._store[conversation_id].append(message)

    def recent(self, conversation_id: str, limit: int = 10, *, context=None) -> list[ChatMessage]:
        with self._lock:
            return list(self._store[conversation_id])[-limit:]
