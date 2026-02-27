# backend/memory/write_queue.py
import asyncio
from collections.abc import Callable, Awaitable
from typing import Any

_queue: asyncio.Queue = asyncio.Queue(maxsize=500)
_worker_task: asyncio.Task | None = None

async def enqueue_write(operation: Callable[[], Awaitable[Any]]) -> Any:
    """Submit a write operation and await its result."""
    future = asyncio.get_event_loop().create_future()
    await _queue.put((operation, future))
    return await future

async def _worker():
    """Single worker that processes writes sequentially."""
    while True:
        operation, future = await _queue.get()
        try:
            result = await operation()
            future.set_result(result)
        except Exception as e:
            future.set_exception(e)
        finally:
            _queue.task_done()

async def start_write_worker():
    global _worker_task
    _worker_task = asyncio.create_task(_worker())
