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

    @asynccontextmanager
    async def _borrow(self):
        async with self.pool.reserve_database() as db:
            yield db

    async def _start_borrower(self):
        entered = asyncio.Event()
        release = asyncio.Event()

        async def borrower():
            async with self._borrow():
                entered.set()
                await release.wait()

        task = asyncio.create_task(borrower())
        await self.acquiring.wait()
        return task, entered, release

    async def test_reservation_releases_itself(self) -> None:
        self.allow_acquisition.set()
        async with self.pool.reserve_database():
            self.assertEqual(self.pool._active_requests, 1)
        self.assertEqual(self.pool._active_requests, 0)
        await asyncio.wait_for(self.pool.close(), 2)

    async def test_unused_reservation_can_be_released(self) -> None:
        reservation = self.pool.reserve_database()
        reservation.release()
        reservation.release()
        self.assertEqual(self.pool._active_requests, 0)
        await asyncio.wait_for(self.pool.close(), 2)

    async def test_reservation_cannot_be_reentered(self) -> None:
        self.allow_acquisition.set()
        reservation = self.pool.reserve_database()
        async with reservation:
            pass
        with self.assertRaises(RuntimeError):
            async with reservation:
                pass

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
            async with self._borrow():
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

    async def test_close_waits_for_cancelled_connection_cleanup(self) -> None:
        """
        Shutdown must not overtake cleanup cancelled while returning a connection.
        """
        cleanup_started = asyncio.Event()
        allow_cleanup = asyncio.Event()
        cleanup_finished = asyncio.Event()

        @asynccontextmanager
        async def connection(*, timeout=None):
            conn = AsyncMock()
            try:
                yield conn
            finally:
                cleanup_started.set()
                try:
                    await allow_cleanup.wait()
                finally:
                    cleanup_finished.set()

        self.pool._pool.connection = connection
        self.allow_acquisition.set()

        async def borrower():
            async with self.pool.reserve_database():
                pass

        task = asyncio.create_task(borrower())
        await asyncio.wait_for(cleanup_started.wait(), 2)
        closing = asyncio.create_task(self.pool.close())
        await asyncio.sleep(0)
        self.pool._pool.close.assert_not_awaited()

        task.cancel()
        try:
            with self.assertRaises(asyncio.CancelledError):
                await asyncio.wait_for(task, 2)
            # Cancellation of the borrower must not let shutdown overtake
            # completion of the underlying connection's cleanup.
            self.assertTrue(cleanup_finished.is_set())
            await asyncio.wait_for(closing, 2)
        finally:
            allow_cleanup.set()
            if not closing.done():
                closing.cancel()
            await asyncio.gather(closing, return_exceptions=True)

    async def test_concurrent_closes_close_pool_once(self) -> None:
        await asyncio.gather(self.pool.close(), self.pool.close())
        self.pool._pool.close.assert_awaited_once()
