"""内存 SOP 存储及按会话保存的执行状态（端口实现）。"""
import threading

from ..application.ports import SopStore
from ..domain.models import SopDefinition, SopExecutionState


class MemorySopStore(SopStore):
    def __init__(self, definitions: list[SopDefinition] | None = None):
        self._lock = threading.Lock()
        self._definitions = {f"{d.sop_id}:{d.version}": d for d in (definitions or [])}
        self._states: dict[tuple[str, str, str], SopExecutionState] = {}

    @staticmethod
    def _state_key(conversation_id: str, context) -> tuple[str, str, str]:
        tenant_id = getattr(context, "tenant_id", "") if context is not None else ""
        user_id = getattr(context, "user_id", "") if context is not None else ""
        return tenant_id, user_id, conversation_id

    def register(self, definition: SopDefinition) -> None:
        with self._lock:
            self._definitions[f"{definition.sop_id}:{definition.version}"] = definition

    def find(self, sop_id: str, version: str | None = None, *, context=None) -> SopDefinition | None:
        with self._lock:
            if version is not None:
                return self._definitions.get(f"{sop_id}:{version}")
            candidates = [d for key, d in self._definitions.items()
                          if key.startswith(f"{sop_id}:")]
            return max(candidates, key=lambda d: d.version) if candidates else None

    def search(self, query: str, *, context=None) -> list[SopDefinition]:
        with self._lock:
            lowered = query.lower()
            return [d for d in self._definitions.values()
                    if any(term in d.title.lower() or term in d.sop_id.lower()
                           for term in lowered.split() if term)]

    def get_state(self, conversation_id: str, *, context=None) -> SopExecutionState | None:
        with self._lock:
            return self._states.get(self._state_key(conversation_id, context))

    def save_state(self, conversation_id: str, state: SopExecutionState, *, context=None) -> None:
        with self._lock:
            self._states[self._state_key(conversation_id, context)] = state
