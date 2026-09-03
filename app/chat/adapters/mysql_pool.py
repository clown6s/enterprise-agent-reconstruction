"""供聊天适配器共享的小型 MySQL 连接池。"""
import queue
import threading
from collections.abc import Callable
from functools import wraps
from typing import TypeVar

import pymysql

from ..domain.exceptions import AppError, ConversationError

T = TypeVar("T")


def mysql_errors(fn):
    """将底层基础设施故障包装为 ConversationError，同时保留领域异常（AppError）。"""
    @wraps(fn)
    def wrapper(self, *args, **kwargs):
        try:
            return fn(self, *args, **kwargs)
        except (AppError, ConversationError):
            raise
        except Exception as exc:
            raise ConversationError(f"Chat MySQL 调用失败: {type(exc).__name__}") from exc
    return wrapper


class MysqlPool:
    def __init__(self, *, host: str, port: int, user: str, password: str,
                 database: str, min_pool: int = 1, max_pool: int = 8,
                 connect_timeout: float = 10.0):
        if min_pool < 0 or max_pool < 1 or min_pool > max_pool:
            raise ValueError("MySQL 连接池参数无效")
        self._config = dict(host=host, port=int(port), user=user, password=password,
                            database=database, charset="utf8mb4",
                            connect_timeout=connect_timeout,
                            cursorclass=pymysql.cursors.DictCursor,
                            autocommit=False)
        self._pool = queue.Queue(maxsize=max_pool)
        self._max_pool = max_pool
        self._created = 0
        self._active = 0
        self._closed = False
        self._lock = threading.Lock()
        for _ in range(min_pool):
            self._pool.put(self._connect())
            self._created += 1

    def _connect(self):
        return pymysql.connect(**self._config)

    def acquire(self):
        with self._lock:
            if self._closed:
                raise RuntimeError("Chat MySQL 连接池已关闭")
        try:
            conn = self._pool.get_nowait()
            try:
                conn.ping(reconnect=True)
            except Exception:
                self._close_connection(conn)
                with self._lock:
                    self._created -= 1
                conn = self._connect()
                with self._lock:
                    self._created += 1
        except queue.Empty:
            with self._lock:
                can_create = self._created < self._max_pool
            if can_create:
                conn = self._connect()
                with self._lock:
                    self._created += 1
            else:
                conn = self._pool.get(timeout=30)
        with self._lock:
            self._active += 1
        return conn

    def release(self, conn) -> None:
        with self._lock:
            self._active = max(0, self._active - 1)
            closed = self._closed
        if closed:
            self._close_connection(conn)
            return
        try:
            self._pool.put_nowait(conn)
        except queue.Full:
            self._close_connection(conn)
            with self._lock:
                self._created = max(0, self._created - 1)

    @staticmethod
    def _close_connection(conn) -> None:
        try:
            conn.close()
        except Exception:
            pass

    def run(self, fn: Callable[..., T], *args, **kwargs) -> T:
        conn = self.acquire()
        try:
            result = fn(conn, *args, **kwargs)
            return result
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            raise
        finally:
            self.release(conn)

    def close(self) -> None:
        with self._lock:
            self._closed = True
        while True:
            try:
                self._close_connection(self._pool.get_nowait())
            except queue.Empty:
                break
