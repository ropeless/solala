import asyncio
from enum import IntEnum
from typing import Any
from weakref import WeakKeyDictionary

from solala.utils.async_rlock import AsyncRLock


class LockRank(IntEnum):
    """
    Define the acquisition order of Solala's shared-state locks.
    """
    CONNECTIONS = 10
    CONTROL = 20
    CACHE = 30


class OrderedAsyncRLock(AsyncRLock):
    """
    Provide a reentrant asyncio lock with task-local acquisition ordering.

    A task may acquire a new lock only if its rank is not lower than the
    ranks of locks it already holds. Reacquiring an already-owned lock is
    always permitted. Equal ranks are permitted, so callers must assign
    distinct ranks to locks that may be nested.

    Ordering is checked before waiting, avoiding circular waits between
    participating locks. This does not prevent deadlocks caused by other
    synchronization mechanisms.
    """

    _held: WeakKeyDictionary[asyncio.Task[Any], dict['OrderedAsyncRLock', int]] = WeakKeyDictionary()

    def __init__(self, rank: LockRank) -> None:
        super().__init__()
        self.rank = rank

    async def acquire(self) -> bool:
        """
        Acquire the lock after checking the current task's lock ordering.

        Returns:
            True when acquired.

        Raises:
            RuntimeError: If acquiring the lock would violate rank ordering.
        """
        task = asyncio.current_task()
        if task is None:
            raise RuntimeError('OrderedAsyncRLock requires a running asyncio task')

        held = self._held.get(task)
        if held is not None and self not in held:
            highest = max((lock.rank for lock in held), default=None)
            if highest is not None and self.rank < highest:
                raise RuntimeError(
                    f'Lock order violation: cannot acquire {self.rank.name} '
                    f'while holding {highest.name}'
                )

        await super().acquire()
        if held is None:
            held = {}
            self._held[task] = held
        held[self] = held.get(self, 0) + 1
        return True

    def release(self) -> None:
        """
        Release one acquisition and update the task's held-lock record.
        """
        task = asyncio.current_task()
        super().release()
        assert task is not None
        held = self._held[task]
        count = held[self] - 1
        if count:
            held[self] = count
        else:
            del held[self]
            if not held:
                del self._held[task]
