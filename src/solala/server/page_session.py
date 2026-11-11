import asyncio
from functools import partial
from typing import List, Callable, Awaitable

from solala.control_loop import control_loop
from solala.control_loop.loop_listener import LoopListener
from solala.logger import LOGGER


class PageSession:
    """
    Own resources that should exist only while a page is active.
    """

    def __init__(self) -> None:
        self._cleanup: List[Callable[[], Awaitable[None] | None]] = []
        self._closed = False

    def add_cleanup(self, cleanup: Callable[[], Awaitable[None] | None]) -> None:
        if self._closed:
            raise RuntimeError('Cannot add resources to a closed page session')
        self._cleanup.append(cleanup)

    async def add_control_listener(self, listener: LoopListener) -> None:
        await control_loop.add_control_loop_listener(listener)
        self.add_cleanup(partial(control_loop.remove_control_loop_listener, listener))

    async def add_database_listener(self, listener: LoopListener) -> None:
        await control_loop.add_database_loop_listener(listener)
        self.add_cleanup(partial(control_loop.remove_database_loop_listener, listener))

    def add_task(self, task: asyncio.Task) -> None:
        async def cancel_task() -> None:
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        self.add_cleanup(cancel_task)

    def add_timer(self, timer) -> None:
        self.add_cleanup(timer.cancel)

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        while self._cleanup:
            cleanup = self._cleanup.pop()
            try:
                result = cleanup()
                if asyncio.iscoroutine(result) or isinstance(result, asyncio.Future):
                    await result
            except Exception:
                LOGGER.exception('Error cleaning up page resource')
