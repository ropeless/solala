import asyncio
import unittest
from unittest.mock import AsyncMock

from solala.database.solala_database_connections import SolalaDatabaseConnections


class DatabaseConnectionLifecycleTests(unittest.IsolatedAsyncioTestCase):
    """Exercise pool lifetime coordination without a PostgreSQL server."""

    def setUp(self) -> None:
        self.pool = SolalaDatabaseConnections(role='test', password='test')
        self.pool._pool.close = AsyncMock()

    async def test_close_waits_for_active_lease(self) -> None:
        lease = self.pool.reserve()
        async with lease:
            closing = asyncio.create_task(self.pool.close())
            await asyncio.sleep(0)
            self.assertFalse(closing.done())
            self.pool._pool.close.assert_not_awaited()
        await closing
        self.pool._pool.close.assert_awaited_once()

    async def test_close_rejects_new_borrowers(self) -> None:
        lease = self.pool.reserve()
        async with lease:
            closing = asyncio.create_task(self.pool.close())
            await asyncio.sleep(0)
            with self.assertRaises(ConnectionError):
                self.pool.reserve()
        await closing

    async def test_cancelled_borrower_releases_lease(self) -> None:
        entered = asyncio.Event()

        async def borrower() -> None:
            async with self.pool.reserve():
                entered.set()
                await asyncio.Event().wait()

        task = asyncio.create_task(borrower())
        await entered.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        await self.pool.close()
        self.pool._pool.close.assert_awaited_once()

    async def test_concurrent_closes_close_pool_once(self) -> None:
        await asyncio.gather(self.pool.close(), self.pool.close())
        self.pool._pool.close.assert_awaited_once()
