import asyncio
import unittest

from solala.utils.async_rlock import AsyncRLock


class AsyncRLockTestCase(unittest.IsolatedAsyncioTestCase):

    async def test_reentrant_acquire_requires_matching_releases(self):
        lock = AsyncRLock()

        self.assertTrue(await lock.acquire())
        self.assertTrue(await lock.acquire())

        lock.release()
        # The first release must not let another task enter.
        acquired = asyncio.Event()

        async def waiter():
            async with lock:
                acquired.set()

        task = asyncio.create_task(waiter())
        await asyncio.sleep(0)
        self.assertFalse(acquired.is_set())

        lock.release()
        await asyncio.wait_for(task, timeout=1)
        self.assertTrue(acquired.is_set())

    async def test_competing_tasks_are_excluded(self):
        lock = AsyncRLock()
        entered = asyncio.Event()
        order = []

        async def worker():
            entered.set()
            async with lock:
                order.append('worker')

        async with lock:
            task = asyncio.create_task(worker())
            await entered.wait()
            await asyncio.sleep(0)
            self.assertEqual(order, [])

        await asyncio.wait_for(task, timeout=1)
        self.assertEqual(order, ['worker'])

    async def test_non_owner_cannot_release_lock(self):
        lock = AsyncRLock()
        acquired = asyncio.Event()
        release_attempted = asyncio.Event()

        async def owner():
            async with lock:
                acquired.set()
                await release_attempted.wait()

        task = asyncio.create_task(owner())
        await acquired.wait()

        with self.assertRaisesRegex(RuntimeError, 'not owned'):
            lock.release()

        release_attempted.set()
        await asyncio.wait_for(task, timeout=1)

    def test_release_outside_asyncio_task_raises(self):
        lock = AsyncRLock()

        with self.assertRaisesRegex(RuntimeError, 'not owned'):
            lock.release()

    async def test_cancelled_waiter_does_not_corrupt_lock(self):
        lock = AsyncRLock()
        waiting = asyncio.Event()

        async def waiter():
            waiting.set()
            await lock.acquire()

        await lock.acquire()
        task = asyncio.create_task(waiter())
        await waiting.wait()
        await asyncio.sleep(0)

        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task

        lock.release()

        # A subsequent task must still be able to acquire the lock.
        async with lock:
            pass

    async def test_context_manager_releases_after_exception(self):
        lock = AsyncRLock()

        with self.assertRaisesRegex(ValueError, 'test exception'):
            async with lock:
                raise ValueError('test exception')

        async with asyncio.timeout(1):
            async with lock:
                pass


if __name__ == '__main__':
    unittest.main()
