"""同步聊天应用端口的异步传输桥接。"""
import asyncio
from collections.abc import Callable
from functools import partial
from typing import TypeVar

T = TypeVar("T")


async def run_sync(fn: Callable[..., T], /, *args, **kwargs) -> T:
    """在线程中执行阻塞型应用用例，避免阻塞 MCP 的事件循环。"""
    return await asyncio.to_thread(partial(fn, *args, **kwargs))


class LazyService:
    """为挂载的 MCP 应用延迟创建并缓存服务。

    挂载 MCP 子应用时不得在导入 FastAPI 模块的过程中连接外部系统。
    因此提供者在首次使用时才被调用一次。
    """

    def __init__(self, provider: Callable[[], T]):
        self._provider = provider
        self._service: T | None = None
        self._lock = __import__("threading").Lock()

    def get(self) -> T:
        """获取服务实例，必要时延迟创建（线程安全，只创建一次）。"""
        if self._service is None:
            with self._lock:
                if self._service is None:
                    self._service = self._provider()
        return self._service

    def is_loaded(self) -> bool:
        """服务是否已被创建（是否已连接外部系统）。"""
        return self._service is not None

    def close_if_loaded(self) -> None:
        """若服务已创建，则调用其 close() 释放资源；未创建则无操作。"""
        service = self._service
        if service is not None:
            closer = getattr(service, "close", None)
            if callable(closer):
                closer()

    def __getattr__(self, name):
        return getattr(self.get(), name)
