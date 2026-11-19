import asyncio
import inspect
from collections.abc import Awaitable, Callable
from datetime import date
from typing import Any, Protocol

from solala.control_loop import control_loop
from solala.control_loop.loop_listener import LoopListener
from solala.logger import LOGGER
from solala.server.css_colours import Colours


class _CancellableTimer(Protocol):
    """
    Declare the cancellation operation required of page-owned timers.
    """
    def cancel(self) -> None:
        ...


class _SessionListener:
    """
    Adapt a UI listener so its updates cannot outlive the owning page session.

    The control loop may schedule updates from a previously captured listener
    snapshot, so unregistering the listener alone is not sufficient.
    """

    def __init__(self, listener: LoopListener) -> None:
        self._listener = listener
        self._closed = False
        self._tasks: set[asyncio.Task[Any]] = set()

    async def update(self) -> None:
        if self._closed:
            return

        task = asyncio.current_task()
        assert task is not None
        self._tasks.add(task)
        try:
            if not self._closed:
                await self._listener.update()
        finally:
            self._tasks.discard(task)

    async def close(self) -> None:
        # Mark closed before yielding, including for already captured snapshots.
        self._closed = True
        tasks = tuple(self._tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)


class PageSession:
    """
    Own resources that should exist only while a page is active and provide
    a delegation back to the session owner for tab selection.

    Registered clean-up callbacks run in reverse registration order when the
    session closes. Callbacks may be synchronous or asynchronous; failures
    are logged without preventing subsequent clean-up.
    """

    def __init__(
            self,
            colours: Colours,
            select_tab: Callable[[str], Awaitable[None]],
            initial_day: date | None = None,
            on_day_change: Callable[[date], Awaitable[None]] | None = None,
    ) -> None:
        """
        Initialise the session with page colours and tab navigation delegation.

        Args:
            colours: Colours used by the page.
            select_tab: Asynchronous callback for selecting a named tab.
            initial_day: Date restored on refresh, if available.
            on_day_change: Callback to persist date navigation.
        """
        self.initial_day = initial_day
        self.on_day_change = on_day_change
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
            cleanup: Synchronous or asynchronous resource clean-up callback.

        Raises:
            RuntimeError: If the session has already closed.
        """
        if self._closed:
            raise RuntimeError('Cannot add resources to a closed page session')
        self._cleanup.append(cleanup)

    async def _add_listener(
            self,
            listener: LoopListener,
            register: Callable[[LoopListener], Awaitable[None]],
            unregister: Callable[[LoopListener], Awaitable[None]],
    ) -> None:
        """
        Register a session-owned listener and clean up in-flight notifications
        before allowing its UI elements to be destroyed.
        """
        if self._closed:
            raise RuntimeError('Cannot add resources to a closed page session')

        wrapped = _SessionListener(listener)
        registration = asyncio.create_task(register(wrapped))
        try:
            await asyncio.shield(registration)
        except asyncio.CancelledError:
            try:
                await registration
            except Exception:
                pass
            else:
                await unregister(wrapped)
            raise

        async def cleanup() -> None:
            # Disable and drain callbacks before unregistering. This also
            # protects against updates scheduled from an older snapshot.
            try:
                await wrapped.close()
            finally:
                await unregister(wrapped)

        if self._closed:
            # The session may have closed while registration was in progress.
            # Its cleanup loop cannot own this listener, so release it here.
            await cleanup()
            raise RuntimeError('Cannot add resources to a closed page session')

        self.add_cleanup(cleanup)

    async def add_control_listener(self, listener: LoopListener) -> None:
        """
        Register a control-loop listener for the lifetime of this page.
        """
        await self._add_listener(
            listener,
            control_loop.add_control_loop_listener,
            control_loop.remove_control_loop_listener,
        )

    async def add_database_listener(self, listener: LoopListener) -> None:
        """
        Register a database-loop listener for the lifetime of this page.
        """
        await self._add_listener(
            listener,
            control_loop.add_database_loop_listener,
            control_loop.remove_database_loop_listener,
        )

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
        Release registered resources in reverse registration order.

        Clean-up exceptions are logged and remaining callbacks still run.
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
