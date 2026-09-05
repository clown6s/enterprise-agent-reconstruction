"""线程安全的雪花 ID 生成器。"""
import os
import threading
import time

_EPOCH_MS = 1577836800000
_WORKER_BITS = 10
_SEQUENCE_BITS = 12
_MAX_WORKER = (1 << _WORKER_BITS) - 1
_MAX_SEQUENCE = (1 << _SEQUENCE_BITS) - 1


class SnowflakeGenerator:
    """生成可排序的全局唯一字符串 ID。"""
    def __init__(self, worker_id: int | None = None):
        value = worker_id if worker_id is not None else int(os.getenv("SNOWFLAKE_WORKER_ID", "0"))
        if value < 0 or value > _MAX_WORKER:
            raise ValueError("雪花 ID worker_id 必须在 0..1023 之间")
        self._worker_id = value
        self._lock = threading.Lock()
        self._last_ms = -1
        self._sequence = 0

    def next_id(self) -> str:
        with self._lock:
            now = int(time.time() * 1000)
            if now < self._last_ms:
                now = self._last_ms
            if now == self._last_ms:
                self._sequence = (self._sequence + 1) & _MAX_SEQUENCE
                if self._sequence == 0:
                    while now <= self._last_ms:
                        now = int(time.time() * 1000)
            else:
                self._sequence = 0
            self._last_ms = now
            value = ((now - _EPOCH_MS) << (_WORKER_BITS + _SEQUENCE_BITS)) \
                | (self._worker_id << _SEQUENCE_BITS) | self._sequence
            return str(value)


_generator = SnowflakeGenerator()


def next_id() -> str:
    """返回下一个雪花 ID。"""
    return _generator.next_id()
