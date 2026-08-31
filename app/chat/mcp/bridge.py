"""Async transport bridge for synchronous chat application ports."""
import asyncio
from collections.abc import Callable
from functools import partial
from typing import TypeVar

T = TypeVar("T")


async def run_sync(fn: Callable[..., T], /, *args, **kwargs) -> T:
    """Run a blocking application use case without blocking MCP's event loop."""
    return await asyncio.to_thread(partial(fn, *args, **kwargs))
