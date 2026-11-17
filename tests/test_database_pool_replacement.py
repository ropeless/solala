import asyncio
import importlib
import unittest
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from solala.database.solala_database_connections import SolalaDatabaseConnections

control = importlib.import_module('solala.control_loop.control_loop')


class DatabasePoolReplacementTests(unittest.IsolatedAsyncioTestCase):
    """
    Test control-loop pool replacement without connecting to PostgreSQL.
    """

    def setUp(self) -> None:
        # Each IsolatedAsyncioTestCase uses a separate event loop. Give each
        # test fresh control state so its asyncio locks cannot retain a binding
        # to the event loop of an earlier test.
        state_patch = patch.object(control, '_CONTROL_STATE', control._ControlState())
        state_patch.start()
        self.addCleanup(state_patch.stop)
        self.settings = SimpleNamespace(
            role='test', password='test', host='localhost',
            port=5432, database_name='solala',
        )
        self.save_patch = patch.object(control, '_save_settings', new_callable=AsyncMock)
        self.save_patch.start()
        self.addCleanup(self.save_patch.stop)
        self.pools = []

    def _pool(self):
        pool = SolalaDatabaseConnections(role='test', password='test')
        pool.open = AsyncMock()
        pool._pool.close = AsyncMock()
        acquiring = asyncio.Event()
        allow_acquisition = asyncio.Event()
        entered = asyncio.Event()
        release = asyncio.Event()
        returned = asyncio.Event()

        @asynccontextmanager
        async def connection(*, timeout=None):
            acquiring.set()
            await allow_acquisition.wait()
            conn = AsyncMock()
            try:
                yield conn
            finally:
                returned.set()

        pool._pool.connection = connection
        self.pools.append(pool)
        return SimpleNamespace(
            pool=pool, acquiring=acquiring, allow_acquisition=allow_acquisition,
            entered=entered, release=release, returned=returned,
        )

    def _install(self, fixture) -> None:
        control._CONTROL_STATE.connections.database_connections = fixture.pool
        control._CONTROL_STATE.connections.database_settings = self.settings

    def _borrow(self, fixture):
        async def operation():
            async with control._database():
                fixture.entered.set()
                await fixture.release.wait()

        return asyncio.create_task(operation())

    async def _replace(self, next_pool):
        with patch.object(control, 'SolalaDatabaseConnections', return_value=next_pool.pool):
            await control.connect_database(self.settings)

    async def test_replace_pool_with_active_request(self) -> None:
        old, new = self._pool(), self._pool()
        self._install(old)
        old.allow_acquisition.set()
        borrower = self._borrow(old)
        await asyncio.wait_for(old.entered.wait(), 2)
        replacing = asyncio.create_task(self._replace(new))
        await asyncio.sleep(0)
        old.pool._pool.close.assert_not_awaited()
        old.release.set()
        await asyncio.wait_for(borrower, 2)
        await asyncio.wait_for(replacing, 2)
        old.pool._pool.close.assert_awaited_once()
        self.assertIs(control._CONTROL_STATE.connections.database_connections, new.pool)

    async def test_replace_pool_during_acquisition(self) -> None:
        old, new = self._pool(), self._pool()
        self._install(old)
        borrower = self._borrow(old)
        await asyncio.wait_for(old.acquiring.wait(), 2)
        replacing = asyncio.create_task(self._replace(new))
        await asyncio.sleep(0)
        old.pool._pool.close.assert_not_awaited()
        old.allow_acquisition.set()
        await asyncio.wait_for(old.entered.wait(), 2)
        old.release.set()
        await asyncio.wait_for(borrower, 2)
        await asyncio.wait_for(replacing, 2)
        self.assertTrue(old.returned.is_set())
        old.pool._pool.close.assert_awaited_once()

    async def test_new_requests_use_replacement_pool(self) -> None:
        old, new = self._pool(), self._pool()
        self._install(old)
        await asyncio.wait_for(self._replace(new), 2)
        new.allow_acquisition.set()
        async with asyncio.timeout(2):
            async with control._database():
                pass
        self.assertTrue(new.acquiring.is_set())
        self.assertFalse(old.acquiring.is_set())

    async def test_disconnect_during_active_request(self) -> None:
        old = self._pool()
        self._install(old)
        old.allow_acquisition.set()
        borrower = self._borrow(old)
        await asyncio.wait_for(old.entered.wait(), 2)
        disconnecting = asyncio.create_task(control.disconnect_database())
        await asyncio.sleep(0)
        old.pool._pool.close.assert_not_awaited()
        old.release.set()
        await asyncio.wait_for(borrower, 2)
        await asyncio.wait_for(disconnecting, 2)
        self.assertIsNone(control._CONTROL_STATE.connections.database_connections)

    async def test_concurrent_replacements(self) -> None:
        old, first, second = self._pool(), self._pool(), self._pool()
        self._install(old)
        old.allow_acquisition.set()
        borrower = self._borrow(old)
        await asyncio.wait_for(old.entered.wait(), 2)
        with patch.object(
                control, 'SolalaDatabaseConnections',
                side_effect=[first.pool, second.pool],
        ):
            replacements = [
                asyncio.create_task(control.connect_database(self.settings))
                for _ in range(2)
            ]
            await asyncio.sleep(0)
            old.release.set()
            await asyncio.wait_for(borrower, 2)
            await asyncio.wait_for(asyncio.gather(*replacements), 2)
        old.pool._pool.close.assert_awaited_once()
        first.pool._pool.close.assert_awaited_once()
        self.assertIs(control._CONTROL_STATE.connections.database_connections, second.pool)

    async def _borrow_needing_connections_lock(self, fixture, proceed):
        """
        Hold a reservation while waiting to reacquire the connections lock.
        """
        async with control._database():
            fixture.entered.set()
            await proceed.wait()
            async with control._connections_state():
                pass

    async def test_disconnect_while_borrower_needs_connections_lock(self) -> None:
        old = self._pool()
        self._install(old)
        old.allow_acquisition.set()
        proceed = asyncio.Event()
        borrower = asyncio.create_task(
            self._borrow_needing_connections_lock(old, proceed)
        )
        await asyncio.wait_for(old.entered.wait(), 2)

        disconnecting = asyncio.create_task(control.disconnect_database())
        # Wait until shutdown has acquired the lock and started draining.
        async with asyncio.timeout(2):
            while not old.pool._closing:
                await asyncio.sleep(0)

        proceed.set()
        try:
            await asyncio.wait_for(
                asyncio.gather(borrower, disconnecting), 1
            )
        finally:
            for task in (borrower, disconnecting):
                if not task.done():
                    task.cancel()
            await asyncio.gather(borrower, disconnecting, return_exceptions=True)

    async def test_replace_while_borrower_needs_connections_lock(self) -> None:
        old, new = self._pool(), self._pool()
        self._install(old)
        old.allow_acquisition.set()
        proceed = asyncio.Event()
        borrower = asyncio.create_task(
            self._borrow_needing_connections_lock(old, proceed)
        )
        await asyncio.wait_for(old.entered.wait(), 2)

        replacing = asyncio.create_task(self._replace(new))
        async with asyncio.timeout(2):
            while not old.pool._closing:
                await asyncio.sleep(0)

        proceed.set()
        try:
            await asyncio.wait_for(
                asyncio.gather(borrower, replacing), 1
            )
        finally:
            for task in (borrower, replacing):
                if not task.done():
                    task.cancel()
            await asyncio.gather(borrower, replacing, return_exceptions=True)

    async def _cancel_during_pool_close(self, replacing: bool) -> None:
        old, new = self._pool(), self._pool()
        self._install(old)
        close_started = asyncio.Event()
        allow_close = asyncio.Event()

        async def slow_close():
            close_started.set()
            await allow_close.wait()

        old.pool._pool.close = AsyncMock(side_effect=slow_close)
        operation = asyncio.create_task(
            self._replace(new) if replacing else control.disconnect_database()
        )
        await asyncio.wait_for(close_started.wait(), 2)
        operation.cancel()
        await asyncio.sleep(0)
        self.assertFalse(operation.done())
        self.assertIsNone(control._CONTROL_STATE.connections.database_connections)
        allow_close.set()
        with self.assertRaises(asyncio.CancelledError):
            await asyncio.wait_for(operation, 2)
        old.pool._pool.close.assert_awaited_once()
        self.assertIsNone(control._CONTROL_STATE.connections.database_connections)

        # The lifecycle lock must also be released after cancellation.
        await asyncio.wait_for(control.disconnect_database(), 2)

    async def test_cancel_disconnect_during_pool_close(self) -> None:
        await self._cancel_during_pool_close(replacing=False)

    async def test_cancel_replacement_during_pool_close(self) -> None:
        await self._cancel_during_pool_close(replacing=True)

    async def test_replacement_after_cancelled_request(self) -> None:
        old, new = self._pool(), self._pool()
        self._install(old)
        borrower = self._borrow(old)
        await asyncio.wait_for(old.acquiring.wait(), 2)
        borrower.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await borrower
        await asyncio.wait_for(self._replace(new), 2)
        old.pool._pool.close.assert_awaited_once()
        self.assertIs(control._CONTROL_STATE.connections.database_connections, new.pool)
