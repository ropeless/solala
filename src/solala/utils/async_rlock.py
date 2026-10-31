import asyncio
import threading


class AsyncRLock:
    def __init__(self) -> None:
        self._rlock = threading.RLock()
        self._alock = None
        self._owner = None
        self._alock_count = 0
        self._rlock_count = 0

    async def acquire(self):
        me = asyncio.current_task()

        self._rlock.acquire()
        if self._rlock_count == 0:
            # first entry this thread acquires the lock
            assert self._alock is None
            assert self._owner is None
            assert self._alock_count == 0
            self._alock = asyncio.Lock()

        self._rlock_count += 1
        if self._owner is me:
            # same thread, same task reenters the lock
            self._alock_count += 1
            return True

        # same thread different task enters the lock
        try:
            await self._alock.acquire()
        except BaseException:
            self._rlock_count -= 1
            if self._rlock_count == 0:
                self._alock = None
            self._rlock.release()
            raise
        assert self._owner is None
        assert self._alock_count == 0
        self._owner = me
        self._alock_count = 1
        return True

    def release(self):
        me = asyncio.current_task()
        if self._owner is not me:
            raise RuntimeError('Cannot release a lock that is not owned')

        self._alock_count -= 1
        if self._alock_count == 0:
            self._owner = None
            self._alock.release()

        self._rlock_count -= 1
        if self._rlock_count == 0:
            self._alock = None
        self._rlock.release()

    async def __aenter__(self):
        await self.acquire()
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        self.release()
