import asyncio
import unittest

from solala.utils.ordered_async_rlock import OrderedAsyncRLock


class OrderedAsyncRLockTestCase(unittest.IsolatedAsyncioTestCase):

    async def test_ascending_order_is_allowed(self):
        connections = OrderedAsyncRLock(10)
        control = OrderedAsyncRLock(20)
        cache = OrderedAsyncRLock(30)

        async with connections:
            async with control:
                async with cache:
                    pass

    async def test_descending_order_is_rejected(self):
        connections = OrderedAsyncRLock(10)
        cache = OrderedAsyncRLock(30)

        async with cache:
            with self.assertRaisesRegex(RuntimeError, 'Lock order violation'):
                await connections.acquire()

        async with connections:
            pass

    async def test_reentrant_acquisition_is_allowed_after_higher_rank(self):
        connections = OrderedAsyncRLock(10)
        control = OrderedAsyncRLock(20)

        async with connections:
            async with control:
                async with connections:
                    pass

    async def test_released_lock_no_longer_affects_order(self):
        connections = OrderedAsyncRLock(10)
        cache = OrderedAsyncRLock(30)

        async with cache:
            pass
        async with connections:
            pass

    async def test_partial_reentrant_release_retains_ordering(self):
        connections = OrderedAsyncRLock(10)
        cache = OrderedAsyncRLock(30)

        await cache.acquire()
        await cache.acquire()
        cache.release()
        try:
            with self.assertRaisesRegex(RuntimeError, 'Lock order violation'):
                await connections.acquire()
        finally:
            cache.release()

        async with connections:
            pass

    async def test_child_task_does_not_inherit_parent_ownership(self):
        connections = OrderedAsyncRLock(10)
        cache = OrderedAsyncRLock(30)

        async def child():
            async with connections:
                pass

        async with cache:
            await asyncio.wait_for(asyncio.create_task(child()), timeout=1)

    async def test_competing_tasks_are_excluded(self):
        lock = OrderedAsyncRLock(20)
        entered = asyncio.Event()

        async def waiter():
            async with lock:
                entered.set()

        async with lock:
            task = asyncio.create_task(waiter())
            await asyncio.sleep(0)
            self.assertFalse(entered.is_set())

        await asyncio.wait_for(task, timeout=1)
        self.assertTrue(entered.is_set())

    async def test_cancelled_waiter_does_not_record_ownership(self):
        lock = OrderedAsyncRLock(20)
        async with lock:
            task = asyncio.create_task(lock.acquire())
            await asyncio.sleep(0)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task

        async with lock:
            pass

    async def test_exception_releases_ownership(self):
        cache = OrderedAsyncRLock(30)
        connections = OrderedAsyncRLock(10)

        with self.assertRaises(ValueError):
            async with cache:
                raise ValueError('test')

        async with connections:
            pass

    async def test_non_owner_release_is_rejected(self):
        lock = OrderedAsyncRLock(20)
        async with lock:
            async def other():
                with self.assertRaisesRegex(RuntimeError, 'not owned'):
                    lock.release()

            await asyncio.create_task(other())


if __name__ == '__main__':
    unittest.main()
