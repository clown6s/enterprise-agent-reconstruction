"""使用单个原子 Lua 脚本的分布式 Redis 限流器。"""
import time
import uuid

import redis


_LUA = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
local member = ARGV[4]
redis.call('ZREMRANGEBYSCORE', key, 0, now - window)
local count = redis.call('ZCARD', key)
if count >= limit then
  redis.call('EXPIRE', key, math.ceil(window / 1000) + 1)
  return 0
end
redis.call('ZADD', key, now, member)
redis.call('EXPIRE', key, math.ceil(window / 1000) + 1)
return 1
"""


class RedisRateLimiter:
    """跨进程安全的固定窗口/滑动窗口限流器。

    ``fail_open`` 需要显式选择：关闭时安全性更高，开启时 Redis 故障期间仍能保持
    服务可用。生产环境应根据实际需求慎重选择。
    """

    def __init__(self, *, host: str, port: int = 6379, password: str = "",
                 db: int = 0, limit: int = 60, window_seconds: int = 60,
                 fail_open: bool = False, client=None):
        if limit < 1 or window_seconds < 1:
            raise ValueError("限流参数必须为正数")
        self.limit = limit
        self.window_seconds = window_seconds
        self.fail_open = fail_open
        self._client = client or redis.Redis(
            host=host, port=int(port), password=password or None, db=int(db),
            decode_responses=True, socket_connect_timeout=2,
            socket_timeout=2,
        )
        self._script = self._client.register_script(_LUA)

    def allow(self, key: str) -> bool:
        if not isinstance(key, str) or not key:
            raise ValueError("限流 key 不能为空")
        now_ms = int(time.time() * 1000)
        redis_key = f"enterprise-agent:ratelimit:{key}"
        try:
            result = self._script(
                keys=[redis_key],
                args=[now_ms, self.window_seconds * 1000,
                      self.limit, uuid.uuid4().hex],
            )
            return bool(int(result))
        except redis.RedisError:
            if self.fail_open:
                return True
            return False

    def ping(self) -> bool:
        """供 readiness 使用的轻量连接检查。"""
        return bool(self._client.ping())

    def close(self) -> None:
        close = getattr(self._client, "close", None)
        if callable(close):
            close()
