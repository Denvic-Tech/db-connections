from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable
from queue import Queue
from threading import Thread
from typing import TypeVar

T = TypeVar("T")


async def maybe_await(value: T | Awaitable[T]) -> T:
    if inspect.isawaitable(value):
        return await value
    return value


def run_async_blocking(awaitable: Awaitable[T]) -> T:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(awaitable)

    result_queue: Queue[tuple[bool, T | BaseException]] = Queue(maxsize=1)

    def runner() -> None:
        try:
            result_queue.put((True, asyncio.run(awaitable)))
        except BaseException as exc:  # pragma: no cover - passthrough from worker thread
            result_queue.put((False, exc))

    thread = Thread(target=runner, daemon=True)
    thread.start()
    thread.join()
    success, payload = result_queue.get()
    if success:
        return payload  # type: ignore[return-value]
    raise payload


def run_maybe_async(value: T | Awaitable[T]) -> T:
    if inspect.isawaitable(value):
        return run_async_blocking(value)
    return value
