import asyncio
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from threading import get_ident
from unittest.mock import AsyncMock, patch

import solala.control.control_loop as control_loop
from solala.settings import (
    DatabaseConnection, DummyConsumerConnection, DummyControllerConnection, DummyPricerConnection,
    DummySolarForecasterConnection, Settings,
)


class SettingsPersistenceTestCase(unittest.IsolatedAsyncioTestCase):
    """
    Verify serialized settings saves and the required lock order.
    """

    async def asyncSetUp(self) -> None:
        self.state = control_loop._ControlState()
        self.tempdir = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.addCleanup(self.tempdir.cleanup)
        self.settings_path = Path(self.tempdir.name) / 'settings.json'
        self.state.settings_persistence.path = self.settings_path
        state_patch = patch.object(control_loop, '_CONTROL_STATE', self.state)
        state_patch.start()
        self.addCleanup(state_patch.stop)

    async def test_concurrent_saves_write_latest_snapshot(self) -> None:
        first_started = asyncio.Event()
        release_first = asyncio.Event()
        written: list[float | None] = []
        original_write = control_loop._write_settings_file

        async def pause_first_write(path: Path, settings: Settings) -> None:
            limit = settings.fixed_limit_pct
            if limit == 25:
                first_started.set()
                await release_first.wait()
            original_write(path, settings)
            written.append(limit)

        with (
            patch.object(control_loop, '_write_settings_in_thread', side_effect=pause_first_write),
            patch.object(control_loop, 'log_info'),
        ):
            async with asyncio.timeout(5), asyncio.TaskGroup() as saves:
                saves.create_task(control_loop.set_control(fixed_limit_pct=25))
                try:
                    await first_started.wait()
                    self.state.control_changed.clear()
                    second = saves.create_task(control_loop.set_control(fixed_limit_pct=35))
                    await self.state.control_changed.wait()
                    self.assertEqual((await control_loop.get_settings()).fixed_limit_pct, 35)
                    self.assertFalse(second.done())
                    self.assertFalse(self.settings_path.exists())
                finally:
                    release_first.set()

        self.assertEqual(written, [25, 35])
        self.assertEqual(Settings.model_validate_json(self.settings_path.read_bytes()).fixed_limit_pct, 35)

    async def test_overlapping_control_save_and_forecaster_replacement_persist_both_changes(self) -> None:
        first = DummySolarForecasterConnection(panel_capacity=7000)
        replacement = DummySolarForecasterConnection(panel_capacity=9000)
        control_write_started = asyncio.Event()
        release_control_write = asyncio.Event()
        replacement_captured = asyncio.Event()
        written: list[Settings] = []
        original_get_settings = control_loop._get_settings
        original_write = control_loop._write_settings_file

        def observe_snapshot(state: control_loop._ControlState) -> Settings:
            settings = original_get_settings(state)
            if settings.forecaster == replacement:
                replacement_captured.set()
            return settings

        async def pause_control_write(path: Path, settings: Settings) -> None:
            if settings.forecaster == first:
                control_write_started.set()
                await release_control_write.wait()
            original_write(path, settings)
            written.append(Settings.model_validate_json(path.read_bytes()))

        self.enterContext(patch.object(control_loop, 'log_info'))
        await control_loop.connect_forecaster(first)
        self.addAsyncCleanup(control_loop.disconnect_forecaster)

        with (
            patch.object(control_loop, '_get_settings', side_effect=observe_snapshot),
            patch.object(control_loop, '_write_settings_in_thread', side_effect=pause_control_write),
        ):
            async with asyncio.timeout(5), asyncio.TaskGroup() as saves:
                saves.create_task(control_loop.set_control(fixed_limit_pct=35))
                try:
                    await control_write_started.wait()
                    replacing = saves.create_task(control_loop.connect_forecaster(replacement))
                    await replacement_captured.wait()
                    current = await control_loop.get_settings()
                    self.assertEqual(current.fixed_limit_pct, 35)
                    self.assertEqual(current.forecaster, replacement)
                    self.assertFalse(replacing.done())
                    self.assertEqual(written, [])
                finally:
                    release_control_write.set()

        self.assertEqual([(settings.fixed_limit_pct, settings.forecaster) for settings in written], [
            (35, first),
            (35, replacement),
        ])
        self.assertEqual(Settings.model_validate_json(self.settings_path.read_bytes()), written[-1])

    async def test_controller_replacement_writes_once(self) -> None:
        first = DummyControllerConnection(inverter_limit=7000)
        replacement = DummyControllerConnection(inverter_limit=9000)
        self.enterContext(patch.object(control_loop, 'log_info'))
        registers = self.enterContext(patch.object(control_loop, '_REGISTERS'))
        registers.update_controller = AsyncMock()
        write_settings = self.enterContext(
            patch.object(control_loop, '_write_settings_file', wraps=control_loop._write_settings_file)
        )

        async with asyncio.timeout(5):
            await control_loop.connect_controller(first)
            self.addAsyncCleanup(control_loop.disconnect_controller)
            write_settings.reset_mock()
            await control_loop.connect_controller(replacement)

        self.assertEqual(Settings.model_validate_json(self.settings_path.read_bytes()).controller, replacement)
        write_settings.assert_called_once()
        registers.update_controller.assert_awaited_with(self.state.connections.controller)

    async def test_failed_controller_registration_persists_disconnect(self) -> None:
        first = DummyControllerConnection(inverter_limit=7000)
        replacement = DummyControllerConnection(inverter_limit=9000)
        self.enterContext(patch.object(control_loop, 'log_info'))
        self.enterContext(patch.object(control_loop, 'log_error'))
        registers = self.enterContext(patch.object(control_loop, '_REGISTERS'))
        registers.update_controller = AsyncMock()
        event_loop_thread = get_ident()
        original_write = control_loop._write_settings_file
        write_threads: list[int] = []

        def record_write(path: Path, settings: Settings) -> None:
            write_threads.append(get_ident())
            original_write(path, settings)

        async with asyncio.timeout(5):
            await control_loop.connect_controller(first)
            self.addAsyncCleanup(control_loop.disconnect_controller)
            registers.update_controller.side_effect = [None, OSError('register discovery failed'), None]
            with (
                patch.object(control_loop, '_write_settings_file', side_effect=record_write),
                self.assertRaises(control_loop.ControlLoopError),
            ):
                await control_loop.connect_controller(replacement)

        self.assertEqual(len(write_threads), 1)
        self.assertNotEqual(write_threads[0], event_loop_thread)
        self.assertIsNone(self.state.connections.controller)
        self.assertIsNone(Settings.model_validate_json(self.settings_path.read_bytes()).controller)

    async def test_database_connect_and_disconnect_write_outside_connections_lock(self) -> None:
        connection = DatabaseConnection(role='test', password='test', host='localhost', database_name='solala')
        loop = asyncio.get_running_loop()
        event_loop_thread = get_ident()
        original_write = control_loop._write_settings_file
        saved_connections: list[DatabaseConnection | None] = []

        def check_write(path: Path, settings: Settings) -> None:
            self.assertNotEqual(get_ident(), event_loop_thread)
            concurrent_read = asyncio.run_coroutine_threadsafe(control_loop.get_settings(), loop)
            try:
                self.assertEqual(concurrent_read.result(timeout=5).database, settings.database)
            finally:
                concurrent_read.cancel()
            original_write(path, settings)
            saved_connections.append(Settings.model_validate_json(path.read_bytes()).database)

        with (
            patch.object(control_loop, '_write_settings_file', side_effect=check_write),
            patch.object(control_loop, 'log_info'),
            patch.object(control_loop, 'log_error') as log_error,
        ):
            await control_loop.connect_database(connection)
            await control_loop.disconnect_database()
            log_error.assert_not_called()

        self.assertEqual(saved_connections, [connection, None])

    async def test_shutdown_closes_database_pool_while_database_save_is_pending(self) -> None:
        connection = DatabaseConnection(role='test', password='test')
        write_started = asyncio.Event()
        release_write = asyncio.Event()
        pool_closed = asyncio.Event()
        close_pool = control_loop._shutdown_database_pool
        write_settings = control_loop._write_settings_file

        async def pause_write(path: Path, settings: Settings) -> None:
            write_started.set()
            await release_write.wait()
            write_settings(path, settings)

        async def observe_close(state: control_loop._ControlState) -> None:
            await close_pool(state)
            pool_closed.set()

        with (
            patch.object(control_loop, '_write_settings_in_thread', side_effect=pause_write),
            patch.object(control_loop, '_shutdown_database_pool', side_effect=observe_close),
            patch.object(control_loop, 'log_info'),
            patch.object(control_loop, 'log_error'),
        ):
            async with asyncio.timeout(5), asyncio.TaskGroup() as tasks:
                tasks.create_task(control_loop.connect_database(connection))
                try:
                    await write_started.wait()
                    shutdown = tasks.create_task(control_loop._shutdown_control_loop(None))
                    await pool_closed.wait()
                    self.assertIsNone(self.state.connections.database_connections)
                    self.assertFalse(shutdown.done())
                finally:
                    release_write.set()

        self.assertEqual(Settings.model_validate_json(self.settings_path.read_bytes()).database, connection)

    async def test_consumer_registration_writes_outside_connections_lock(self) -> None:
        connection = DummyConsumerConnection()
        loop = asyncio.get_running_loop()
        event_loop_thread = get_ident()
        original_write = control_loop._write_settings_file
        self.enterContext(patch.object(control_loop, '_REGISTERS'))
        self.enterContext(patch.object(control_loop, 'log_info'))
        log_error = self.enterContext(patch.object(control_loop, 'log_error'))
        self.addAsyncCleanup(control_loop.disconnect_consumer, 'meter')

        def check_write(path: Path, settings: Settings) -> None:
            self.assertNotEqual(get_ident(), event_loop_thread)
            concurrent_read = asyncio.run_coroutine_threadsafe(control_loop.get_settings(), loop)
            try:
                self.assertEqual(concurrent_read.result(timeout=5).consumers, {'meter': connection})
            finally:
                concurrent_read.cancel()
            original_write(path, settings)

        with patch.object(control_loop, '_write_settings_file', side_effect=check_write) as write:
            await control_loop.connect_consumer('meter', connection)
            write.assert_called_once()
            log_error.assert_not_called()

        self.assertEqual(Settings.model_validate_json(self.settings_path.read_bytes()).consumers, {'meter': connection})

    async def test_consumer_disconnect_writes_outside_connections_lock(self) -> None:
        loop = asyncio.get_running_loop()
        event_loop_thread = get_ident()
        original_write = control_loop._write_settings_file
        self.enterContext(patch.object(control_loop, '_REGISTERS'))
        self.enterContext(patch.object(control_loop, 'log_info'))
        log_error = self.enterContext(patch.object(control_loop, 'log_error'))
        await control_loop.connect_consumer('meter', DummyConsumerConnection())
        self.addAsyncCleanup(control_loop.disconnect_consumer, 'meter')

        async def check_disconnected_settings() -> None:
            async with control_loop._connections_state() as connections:
                self.assertNotIn('meter', connections.consumers_settings)
                self.assertIn('meter', connections.closing_consumers)

        def check_write(path: Path, settings: Settings) -> None:
            self.assertNotEqual(get_ident(), event_loop_thread)
            concurrent_read = asyncio.run_coroutine_threadsafe(check_disconnected_settings(), loop)
            try:
                concurrent_read.result(timeout=5)
            finally:
                concurrent_read.cancel()
            original_write(path, settings)

        with patch.object(control_loop, '_write_settings_file', side_effect=check_write) as write:
            await control_loop.disconnect_consumer('meter')
            write.assert_called_once()
            log_error.assert_not_called()

        self.assertNotIn('meter', self.state.connections.closing_consumers)
        self.assertEqual(Settings.model_validate_json(self.settings_path.read_bytes()).consumers, {})

    async def test_forecaster_replacement_persists_new_connection(self) -> None:
        first = DummySolarForecasterConnection(panel_capacity=7000)
        replacement = DummySolarForecasterConnection(panel_capacity=9000)
        self.enterContext(patch.object(control_loop, 'log_info'))
        log_error = self.enterContext(patch.object(control_loop, 'log_error'))
        write_settings = self.enterContext(
            patch.object(control_loop, '_write_settings_file', wraps=control_loop._write_settings_file)
        )

        async with asyncio.timeout(5):
            await control_loop.connect_forecaster(first)
            self.addAsyncCleanup(control_loop.disconnect_forecaster)
            self.assertEqual(Settings.model_validate_json(self.settings_path.read_bytes()).forecaster, first)

            write_settings.reset_mock()
            await control_loop.connect_forecaster(replacement)
            self.assertEqual(Settings.model_validate_json(self.settings_path.read_bytes()).forecaster, replacement)
            write_settings.assert_called_once()
            log_error.assert_not_called()

    async def test_pricer_replacement_and_disconnect_each_write_once(self) -> None:
        first = DummyPricerConnection(buy_price_min=2)
        replacement = DummyPricerConnection(buy_price_min=3)
        self.enterContext(patch.object(control_loop, 'log_info'))
        log_error = self.enterContext(patch.object(control_loop, 'log_error'))
        write_settings = self.enterContext(
            patch.object(control_loop, '_write_settings_file', wraps=control_loop._write_settings_file)
        )

        async with asyncio.timeout(5):
            await control_loop.connect_pricer(first)
            try:
                write_settings.reset_mock()
                await control_loop.connect_pricer(replacement)
                self.assertEqual(Settings.model_validate_json(self.settings_path.read_bytes()).pricer, replacement)
                write_settings.assert_called_once()
            finally:
                write_settings.reset_mock()
                await control_loop.disconnect_pricer()

            self.assertIsNone(Settings.model_validate_json(self.settings_path.read_bytes()).pricer)
            write_settings.assert_called_once()
            log_error.assert_not_called()

    async def test_settings_snapshot_enforces_lock_order(self) -> None:
        with self.assertRaisesRegex(RuntimeError, 'Lock order violation'):
            async with self.state.control.lock:
                await control_loop.get_settings()

    async def test_forecaster_write_leaves_connections_lock_available(self) -> None:
        connection = DummySolarForecasterConnection()
        self.enterContext(patch.object(control_loop, 'log_info'))
        self.addAsyncCleanup(control_loop.disconnect_forecaster)

        loop = asyncio.get_running_loop()
        original_write = control_loop._write_settings_file

        def check_write(path: Path, settings: Settings) -> None:
            concurrent_read = asyncio.run_coroutine_threadsafe(control_loop.get_settings(), loop)
            try:
                self.assertEqual(concurrent_read.result(timeout=5).forecaster, connection)
            finally:
                concurrent_read.cancel()
            self.assertFalse(self.settings_path.exists())
            original_write(path, settings)

        with patch.object(control_loop, '_write_settings_file', side_effect=check_write) as write:
            await control_loop.connect_forecaster(connection)
            write.assert_called_once()

        self.assertEqual(Settings.model_validate_json(self.settings_path.read_bytes()).forecaster, connection)

    async def test_control_change_releases_connections_lock_before_write(self) -> None:
        loop = asyncio.get_running_loop()
        event_loop_thread = get_ident()
        original_write = control_loop._write_settings_file

        def check_write(path: Path, settings: Settings) -> None:
            self.assertNotEqual(get_ident(), event_loop_thread)
            concurrent_read = asyncio.run_coroutine_threadsafe(control_loop.get_settings(), loop)
            try:
                self.assertEqual(concurrent_read.result(timeout=5).fixed_limit_pct, 35)
            finally:
                concurrent_read.cancel()
            original_write(path, settings)

        with (
            patch.object(control_loop, '_write_settings_file', side_effect=check_write),
            patch.object(control_loop, 'log_info'),
            patch.object(control_loop, 'log_error') as log_error,
        ):
            await control_loop.set_control(fixed_limit_pct=35)
            log_error.assert_not_called()

        self.assertTrue(self.state.control_changed.is_set())
        self.assertEqual(Settings.model_validate_json(self.settings_path.read_bytes()).fixed_limit_pct, 35)

    async def test_startup_writes_applied_settings_once_outside_connections_lock(self) -> None:
        self.state.settings_persistence.path = None
        loop = asyncio.get_running_loop()
        event_loop_thread = get_ident()
        original_write = control_loop._write_settings_file

        def check_write(path: Path, settings: Settings) -> None:
            self.assertNotEqual(get_ident(), event_loop_thread)
            concurrent_read = asyncio.run_coroutine_threadsafe(control_loop.get_settings(), loop)
            try:
                self.assertEqual(concurrent_read.result(timeout=5).fixed_limit_pct, 35)
            finally:
                concurrent_read.cancel()
            original_write(path, settings)

        with (
            patch.object(control_loop, '_write_settings_file', side_effect=check_write) as write,
            patch.object(control_loop, 'log_info'),
            patch.object(control_loop, 'log_error') as log_error,
        ):
            await control_loop._configure_startup(self.settings_path, Settings(fixed_limit_pct=35), force_settings=True)
            write.assert_called_once()
            log_error.assert_not_called()

        self.assertEqual(Settings.model_validate_json(self.settings_path.read_bytes()).fixed_limit_pct, 35)

    async def test_shutdown_saves_pending_consumer_removal_off_loop(self) -> None:
        retained = DummyConsumerConnection()
        self.state.connections.consumers_settings['retained'] = retained
        self.state.connections.closing_consumers['removed'] = asyncio.create_task(asyncio.sleep(0))
        event_loop_thread = get_ident()
        original_write = control_loop._write_settings_file

        def check_write(path: Path, settings: Settings) -> None:
            self.assertNotEqual(get_ident(), event_loop_thread)
            original_write(path, settings)

        with (
            patch.object(control_loop, '_write_settings_file', side_effect=check_write),
            patch.object(control_loop, 'log_info'),
            patch.object(control_loop, 'log_error') as log_error,
        ):
            await control_loop._close_control_loop_resources('test shutdown')
            log_error.assert_not_called()

        self.assertEqual(Settings.model_validate_json(self.settings_path.read_bytes()).consumers, {'retained': retained})
        self.assertIsNone(self.state.settings_persistence.path)

    async def test_shutdown_waits_for_settings_after_cleanup_deadline(self) -> None:
        retained = DummyConsumerConnection()
        self.state.connections.consumers_settings['retained'] = retained

        async def stall_close() -> None:
            await asyncio.Event().wait()

        stalled_close = asyncio.create_task(stall_close())
        self.state.connections.closing_consumers['removed'] = stalled_close
        write_started = asyncio.Event()
        release_write = asyncio.Event()
        deadline_expired = asyncio.Event()
        original_write = control_loop._write_settings_file

        async def pause_write(path: Path, settings: Settings) -> None:
            write_started.set()
            await release_write.wait()
            original_write(path, settings)

        def record_error(message: str) -> None:
            if message.startswith('Control-loop shutdown exceeded'):
                deadline_expired.set()

        with (
            patch.object(control_loop.Constants, 'MAX_SHUTDOWN_TIMEOUT', timedelta(milliseconds=250)),
            patch.object(control_loop, '_write_settings_in_thread', side_effect=pause_write),
            patch.object(control_loop, 'log_info'),
            patch.object(control_loop, 'log_error', side_effect=record_error),
        ):
            shutdown = asyncio.create_task(control_loop._shutdown_control_loop(None))
            try:
                async with asyncio.timeout(5):
                    await deadline_expired.wait()
                    self.assertTrue(write_started.is_set())
                    self.assertTrue(stalled_close.cancelled())
                    self.assertFalse(shutdown.done())
                    self.assertFalse(self.settings_path.exists())
            finally:
                release_write.set()
                await asyncio.wait_for(shutdown, 5)

        self.assertFalse(self.state.connections.shutting_down)
        self.assertEqual(Settings.model_validate_json(self.settings_path.read_bytes()).consumers, {'retained': retained})


if __name__ == '__main__':
    unittest.main()
