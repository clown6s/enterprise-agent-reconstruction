"""In-memory SOP store + per-conversation execution state (port implementation)."""
import threading

from ..application.ports import SopStore
from ..domain.models import SopDefinition, SopExecutionState


class MemorySopStore(SopStore):
    def __init__(self, definitions: list[SopDefinition] | None = None):
        self._lock = threading.Lock()
        self._definitions = {f"{d.sop_id}:{d.version}": d for d in (definitions or [])}
        self._states: dict[str, SopExecutionState] = {}

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
            return self._states.get(conversation_id)

    def save_state(self, conversation_id: str, state: SopExecutionState, *, context=None) -> None:
        with self._lock:
            self._states[conversation_id] = state
