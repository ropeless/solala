import asyncio
import threading


class AsyncRLock:
    def __init__(self):
        # A standard lock is thread-agnostic for releases,
        # allowing any thread pool worker to safely release it.
        self._lock = threading.Lock()

        # Track ownership manually using the current OS thread ID
        self._owner_thread = None
        self._count = 0
        self._internal_thread_lock = threading.Lock()

    async def acquire(self):
        current_thread = threading.get_ident()

        # Step 1: Thread-safely check if the current thread already owns it (Reentrancy)
        with self._internal_thread_lock:
            if self._owner_thread == current_thread:
                self._count += 1
                return True

        # Step 2: If not owned, wait for and acquire the underlying lock in a thread pool
        await asyncio.to_thread(self._lock.acquire)

        # Step 3: Successfully acquired, register ownership
        with self._internal_thread_lock:
            self._owner_thread = current_thread
            self._count = 1
        return True

    def release(self):
        current_thread = threading.get_ident()

        with self._internal_thread_lock:
            if self._owner_thread != current_thread:
                raise RuntimeError("Cannot release a lock owned by another thread/loop")

            self._count -= 1
            if self._count == 0:
                self._owner_thread = None
                # Standard locks can be safely released by any thread worker
                self._lock.release()

    async def __aenter__(self):
        await self.acquire()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        # Note: release() is synchronous now to avoid thread-pool mismatch issues
        self.release()
