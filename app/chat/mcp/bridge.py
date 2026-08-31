"""Async transport bridge for synchronous chat application ports."""
import asyncio
from collections.abc import Callable
from functools import partial
from typing import TypeVar

T = TypeVar("T")


async def run_sync(fn: Callable[..., T], /, *args, **kwargs) -> T:
    """Run a blocking application use case without blocking MCP's event loop."""
    return await asyncio.to_thread(partial(fn, *args, **kwargs))


class LazyService:
    """Lazily create and cache a service for mounted MCP applications.

    Mounting an MCP sub-application must not connect to external systems while
    importing the FastAPI module. The provider is called once, on first use.
    """

    def __init__(self, provider: Callable[[], T]):
        self._provider = provider
        self._service: T | None = None
        self._lock = __import__("threading").Lock()

    def _get(self) -> T:
        if self._service is None:
            with self._lock:
                if self._service is None:
                    self._service = self._provider()
        return self._service

    def __getattr__(self, name):
        return getattr(self._get(), name)
