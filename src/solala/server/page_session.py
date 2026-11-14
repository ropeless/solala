"""
Manage listeners, tasks, and timers belonging to an active GUI page.
"""

import asyncio
import inspect
from functools import partial
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from solala.control_loop import control_loop
from solala.control_loop.loop_listener import LoopListener
from solala.logger import LOGGER
from solala.server.css_colours import Colours


class _CancellableTimer(Protocol):
    """
    Describe the cancellation operation required of page-owned timers.
    """
    def cancel(self) -> None:
        ...


class PageSession:
    """
    Own resources that should exist only while a page is active.

    Registered cleanup callbacks run in reverse registration order when the
    session closes. Callbacks may be synchronous or asynchronous; failures
    are logged without preventing subsequent cleanup.
    """

    def __init__(
            self,
            colours: Colours,
            select_tab: Callable[[str], Awaitable[None]],
    ) -> None:
        """
        Initialise the session with page colours and tab navigation.

        Args:
            colours: Colours used by the page.
            select_tab: Asynchronous callback for selecting a named tab.
        """
        self._cleanup: list[Callable[[], Awaitable[None] | None]] = []
        self._closed: bool = False
        self._colours: Colours = colours
        self._select_tab: Callable[[str], Awaitable[None]] = select_tab

    @property
    def colours(self) -> Colours:
        """
        Return the page's colour palette.
        """
        return self._colours

    def add_cleanup(self, cleanup: Callable[[], Awaitable[None] | None]) -> None:
        """
        Register a callback to run when the session closes.

        Args:
            cleanup: Synchronous or asynchronous resource cleanup callback.

        Raises:
            RuntimeError: If the session has already closed.
        """
        if self._closed:
            raise RuntimeError('Cannot add resources to a closed page session')
        self._cleanup.append(cleanup)

    async def add_control_listener(self, listener: LoopListener) -> None:
        """
        Register a control-loop listener for the lifetime of this page.

        If registration is cancelled, await its completion and unregister the
        listener if registration succeeded.

        Args:
            listener: Control-loop listener to register.
        """
        registration = asyncio.create_task(control_loop.add_control_loop_listener(listener))
        try:
            await asyncio.shield(registration)
        except asyncio.CancelledError:
            try:
                await registration
            except Exception:
                pass
            else:
                await control_loop.remove_control_loop_listener(listener)
            raise
        self.add_cleanup(partial(control_loop.remove_control_loop_listener, listener))

    async def add_database_listener(self, listener: LoopListener) -> None:
        """
        Register a database-loop listener for the lifetime of this page.

        If registration is cancelled, await its completion and unregister the
        listener if registration succeeded.

        Args:
            listener: Database-loop listener to register.
        """
        registration = asyncio.create_task(control_loop.add_database_loop_listener(listener))
        try:
            await asyncio.shield(registration)
        except asyncio.CancelledError:
            try:
                await registration
            except Exception:
                pass
            else:
                await control_loop.remove_database_loop_listener(listener)
            raise
        self.add_cleanup(partial(control_loop.remove_database_loop_listener, listener))

    def add_task(self, task: asyncio.Task[Any]) -> None:
        """
        Arrange for an unfinished task to be cancelled and awaited on close.

        Args:
            task: Task owned by the page session.
        """
        async def cancel_task() -> None:
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        self.add_cleanup(cancel_task)

    def add_timer(self, timer: _CancellableTimer) -> None:
        """
        Arrange for the timer to be cancelled when the page closes.

        Args:
            timer: Object exposing a synchronous `cancel()` method.
        """
        self.add_cleanup(timer.cancel)

    async def select_tab(self, tab_name: str) -> None:
        """
        Select a tab through the page's navigation callback.

        Args:
            tab_name: Name of the tab to activate.
        """
        await self._select_tab(tab_name)

    async def close(self) -> None:
        """
        Release registered resources once, in reverse registration order.

        Cleanup exceptions are logged and remaining callbacks still run.
        Subsequent calls have no effect.
        """
        if self._closed:
            return
        self._closed = True
        while self._cleanup:
            cleanup = self._cleanup.pop()
            try:
                result = cleanup()
                if inspect.isawaitable(result):
                    await result
            except Exception:
                LOGGER.exception('Error cleaning up page resource')
