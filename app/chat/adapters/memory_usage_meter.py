"""In-memory usage meter; records counts only, never raw content."""
from collections import defaultdict
import threading


class MemoryUsageMeter:
    def __init__(self):
        self._lock = threading.Lock()
        self._stats = defaultdict(lambda: {
            "requests": 0, "input_chars": 0, "output_chars": 0, "duration_ms": 0,
        })

    def record(self, key: str, *, input_chars: int, output_chars: int,
               duration_ms: int) -> None:
        if not isinstance(key, str) or not key:
            raise ValueError("usage key 不能为空")
        with self._lock:
            row = self._stats[key]
            row["requests"] += 1
            row["input_chars"] += max(0, int(input_chars))
            row["output_chars"] += max(0, int(output_chars))
            row["duration_ms"] += max(0, int(duration_ms))

    def snapshot(self) -> dict[str, dict[str, int]]:
        with self._lock:
            return {key: dict(value) for key, value in self._stats.items()}

    def close(self) -> None:
        with self._lock:
            self._stats.clear()
