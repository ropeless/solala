import asyncio
from types import TracebackType
from typing import Self, Any


class AsyncRLock:
    """
    Provide a reentrant lock for asyncio tasks.

    The owning task may acquire the lock repeatedly without blocking. Each
    successful acquisition must be matched by a release before another task
    can acquire it. Only the owning task may release the lock.

    The lock must be used within a single asyncio event loop.

    An AsyncRLock can be acquired and released through an asynchronous context manager.
    """

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._owner: asyncio.Task[Any] | None = None
        self._count = 0

    async def acquire(self) -> bool:
        """
        Acquire the lock, waiting if another task currently owns it.

        Repeated acquisitions by the owning task increment the hold count.

        Returns:
            True once the lock has been acquired.
        """
        me = asyncio.current_task()
        assert me is not None

        if self._owner is me:
            # The current task already owns the lock.
            self._count += 1
            return True

        await self._lock.acquire()
        self._owner = me
        self._count = 1
        return True

    def release(self) -> None:
        """
        Release one level of ownership held by the current task.

        Raises:
            RuntimeError: If the current task does not own the lock.
        """
        me = asyncio.current_task()
        if me is None or self._owner is not me:
            raise RuntimeError('Cannot release a lock that is not owned')

        self._count -= 1
        if self._count == 0:
            self._owner = None
            self._lock.release()

    async def __aenter__(self) -> Self:
        """
        Acquire the lock on entry to an asynchronous context manager.

        Returns:
            This lock instance.
        """
        await self.acquire()
        return self

    async def __aexit__(
            self,
            exc_type: type[BaseException] | None,
            exc_value: BaseException | None,
            traceback: TracebackType | None,
    ) -> None:
        """
        Release one level of ownership when leaving the context manager.
        """
        self.release()
