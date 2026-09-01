import pytest
import redis

from app.chat.adapters.redis_rate_limiter import RedisRateLimiter


class FakeRedisError(redis.RedisError):
    pass


class FakeClient:
    def __init__(self, results):
        self._results = list(results)
        self.script = None
        self.closed = False

    def register_script(self, _lua):
        self.script = "registered"
        return self._run

    def _run(self, *, keys, args):
        return self._results.pop(0) if self._results else 1

    def close(self):
        self.closed = True


def test_redis_limiter_allows_and_denies():
    client = FakeClient([1, 1, 0])
    limiter = RedisRateLimiter(host="h", limit=2, window_seconds=60, client=client)
    assert limiter.allow("u") is True
    assert limiter.allow("u") is True
    assert limiter.allow("u") is False


def test_redis_limiter_fail_closed_on_error():
    class _Err:
        def register_script(self, _lua):
            return self._run
        def _run(self, *, keys, args):
            raise FakeRedisError("down")
    limiter = RedisRateLimiter(host="h", client=_Err(), fail_open=False)
    assert limiter.allow("u") is False


def test_redis_limiter_fail_open_on_error():
    class _Err:
        def register_script(self, _lua):
            return self._run
        def _run(self, *, keys, args):
            raise FakeRedisError("down")
    limiter = RedisRateLimiter(host="h", client=_Err(), fail_open=True)
    assert limiter.allow("u") is True


def test_redis_limiter_rejects_empty_key():
    limiter = RedisRateLimiter(host="h", client=FakeClient([]))
    with pytest.raises(ValueError):
        limiter.allow("")
