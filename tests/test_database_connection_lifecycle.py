import asyncio
import unittest
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

from solala.database.solala_database_connections import SolalaDatabaseConnections


class DatabaseConnectionLifecycleTests(unittest.IsolatedAsyncioTestCase):
    """
    Verify graceful database pool shutdown without a PostgreSQL server.
    """

    def setUp(self) -> None:
        self.pool = SolalaDatabaseConnections(role='test', password='test')
        self.pool.open = AsyncMock()
        self.pool._pool.close = AsyncMock()
        self.acquiring = asyncio.Event()
        self.allow_acquisition = asyncio.Event()
        self.returned = asyncio.Event()

        @asynccontextmanager
        async def connection(*, timeout=None):
            self.acquiring.set()
            await self.allow_acquisition.wait()
            conn = AsyncMock()
            try:
                yield conn
            finally:
                self.returned.set()

        self.pool._pool.connection = connection

    async def _start_borrower(self):
        entered = asyncio.Event()
        release = asyncio.Event()

        async def borrower():
            async with self.pool.solala_database():
                entered.set()
                await release.wait()

        task = asyncio.create_task(borrower())
        await self.acquiring.wait()
        return task, entered, release

    async def test_close_waits_for_active_request(self) -> None:
        task, entered, release = await self._start_borrower()
        self.allow_acquisition.set()
        await entered.wait()
        closing = asyncio.create_task(self.pool.close())
        await asyncio.sleep(0)
        self.pool._pool.close.assert_not_awaited()
        release.set()
        await task
        await closing
        self.pool._pool.close.assert_awaited_once()

    async def test_close_rejects_new_borrowers(self) -> None:
        task, entered, release = await self._start_borrower()
        self.allow_acquisition.set()
        await entered.wait()
        closing = asyncio.create_task(self.pool.close())
        await asyncio.sleep(0)
        with self.assertRaises(ConnectionError):
            async with self.pool.solala_database():
                pass
        release.set()
        await task
        await closing

    async def test_cancelled_request_allows_close(self) -> None:
        task, _, _ = await self._start_borrower()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        await self.pool.close()
        self.pool._pool.close.assert_awaited_once()

    async def test_close_waits_during_acquisition(self) -> None:
        task, entered, release = await self._start_borrower()
        closing = asyncio.create_task(self.pool.close())
        await asyncio.sleep(0)
        self.pool._pool.close.assert_not_awaited()
        self.allow_acquisition.set()
        await entered.wait()
        release.set()
        await task
        await closing
        self.assertTrue(self.returned.is_set())
        self.pool._pool.close.assert_awaited_once()

    async def test_concurrent_closes_close_pool_once(self) -> None:
        await asyncio.gather(self.pool.close(), self.pool.close())
        self.pool._pool.close.assert_awaited_once()
