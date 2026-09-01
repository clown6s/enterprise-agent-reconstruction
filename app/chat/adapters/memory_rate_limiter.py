"""Thread-safe fixed-window rate limiter for tests and single-process use."""
import threading
import time


class MemoryRateLimiter:
    def __init__(self, *, limit: int = 60, window_seconds: int = 60):
        if limit < 1 or window_seconds < 1:
            raise ValueError("限流参数必须为正数")
        self.limit = limit
        self.window_seconds = window_seconds
        self._lock = threading.Lock()
        self._windows: dict[str, tuple[int, int]] = {}

    def allow(self, key: str) -> bool:
        now = int(time.time())
        bucket = now // self.window_seconds
        with self._lock:
            old_bucket, count = self._windows.get(key, (bucket, 0))
            if old_bucket != bucket:
                count = 0
            if count >= self.limit:
                self._windows[key] = (bucket, count)
                return False
            self._windows[key] = (bucket, count + 1)
            return True

    def close(self) -> None:
        with self._lock:
            self._windows.clear()
