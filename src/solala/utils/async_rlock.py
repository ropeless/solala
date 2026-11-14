import asyncio
from typing import Self, Any


class AsyncRLock:
    """
    A reentrant lock for asynchronous tasks. The same task may
    re-acquire a lock that it currently holds.

    This lock must only be used from a single asyncio event loop.
    """

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._owner: asyncio.Task[Any] | None = None
        self._count = 0

    async def acquire(self) -> bool:
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
        me = asyncio.current_task()
        if me is None or self._owner is not me:
            raise RuntimeError('Cannot release a lock that is not owned')

        self._count -= 1
        if self._count == 0:
            self._owner = None
            self._lock.release()

    async def __aenter__(self) -> Self:
        await self.acquire()
        return self

    async def __aexit__(self, exc_type, exc_value, traceback) -> None:
        self.release()
