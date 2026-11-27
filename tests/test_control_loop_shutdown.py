import asyncio
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import create_autospec, patch

from solala.control import control_loop
from solala.control.power_consumer_manager import PowerConsumerManager
from solala.database.solala_database_connections import SolalaDatabaseConnections
from solala.delegates.power_consumer.dummy_power_consumer.dummy_power_consumer import DummyPowerConsumer
from solala.delegates.power_controller.dummy_power_controller.dummy_power_controller import DummyPowerController
from solala.delegates.power_pricer.dummy_power_pricer.dummy_power_pricer import DummyPowerPricer
from solala.delegates.solar_forecaster.dummy_solar_forecaster.dummy_solar_forecaster import DummySolarForecaster
from solala.settings import (
    ConsumerConnection, DatabaseConnection, DummyConsumerConnection, DummyControllerConnection,
    DummyPricerConnection, DummySolarForecasterConnection, Settings,
)


class ControlLoopShutdownTestCase(unittest.IsolatedAsyncioTestCase):
    """
    Ensure background tasks finish before control_loop returns or raises.
    """

    async def test_normal_exit_cancels_and_awaits_database_task(self) -> None:
        await self._check_shutdown(None)

    async def test_control_loop_failure_cancels_and_awaits_database_task(self) -> None:
        with self.assertRaisesRegex(RuntimeError, 'control failed'):
            await self._check_shutdown(RuntimeError('control failed'))

    async def test_control_loop_cancellation_cancels_and_awaits_database_task(self) -> None:
        with self.assertRaises(asyncio.CancelledError):
            await self._check_shutdown(asyncio.CancelledError())

    async def test_shutdown_budget_reports_stalled_consumer_and_closes_other_delegates(self) -> None:
        state = control_loop._ControlState()
        reading = asyncio.Event()
        release = asyncio.Event()
        consumers: dict[str, ConsumerConnection] = {'slow': DummyConsumerConnection()}

        async def stalled_read(_: DummyPowerConsumer) -> None:
            reading.set()
            await release.wait()
            raise ConnectionError('read failed')

        async def main_loop() -> None:
            state.connections.consumers['slow'].try_get_status()
            await reading.wait()
            control_loop.exit_control_loop()

        with (
            patch.object(control_loop.Constants, 'MAX_SHUTDOWN_TIMEOUT', timedelta(milliseconds=50), create=True),
            patch.object(control_loop, '_CONTROL_STATE', state),
            patch.object(control_loop, '_REGISTERS'),
            patch.object(control_loop, '_control_loop', side_effect=main_loop),
            patch.object(DummyPowerConsumer, 'get_status', autospec=True, side_effect=stalled_read),
            patch.object(DummySolarForecaster, 'close', autospec=True) as close_forecaster,
            patch.object(control_loop, 'log_info') as log_info,
            patch.object(control_loop, 'log_error') as log_error,
        ):
            task = asyncio.create_task(control_loop.control_loop(
                settings=Settings(consumers=consumers, forecaster=DummySolarForecasterConnection()),
                database_write=False,
            ))
            try:
                await asyncio.wait_for(asyncio.shield(task), 1)
                close_forecaster.assert_awaited_once()
                self.assertTrue(any("'slow'" in call.args[0] for call in log_error.call_args_list))
                log_info.assert_any_call('Closed solar forecaster during control-loop shutdown')
            finally:
                release.set()
                await task
                await asyncio.gather(*state.connections.closing_consumers.values(), return_exceptions=True)

    async def test_shutdown_closes_connections_and_restarts_from_saved_settings(self) -> None:
        consumers: dict[str, ConsumerConnection] = {
            'charger': DummyConsumerConnection(),
            'outlet': DummyConsumerConnection(),
        }
        settings = Settings(
            consumers=consumers,
            controller=DummyControllerConnection(),
            pricer=DummyPricerConnection(),
            forecaster=DummySolarForecasterConnection(),
            database=DatabaseConnection(role='test', password='test'),
        )
        state = control_loop._ControlState()
        registers = control_loop.RegisterManager(
            state.control.control_mode, control_loop.get_power_status, control_loop.get_price_now
        )
        runs: list[dict[str, PowerConsumerManager]] = []
        saved_settings: list[bytes] = []
        pools = [create_autospec(SolalaDatabaseConnections, instance=True) for _ in range(2)]
        for pool in pools:
            pool.get_connection_info.return_value = {}

        async def main_loop() -> None:
            runs.append(state.connections.consumers.copy())
            saved_settings.append(settings_path.read_bytes())
            self.assertIn('status/power/consumer/charger/on', registers.get_register_bank())
            control_loop.exit_control_loop()

        with (
            tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory,
            patch.object(control_loop, '_CONTROL_STATE', state),
            patch.object(control_loop, '_REGISTERS', registers),
            patch.object(control_loop, '_control_loop', side_effect=main_loop),
            patch('solala.control.control_loop.SolalaDatabaseConnections', side_effect=pools),
            patch.object(DummyPowerController, 'close', autospec=True) as close_controller,
            patch.object(DummyPowerPricer, 'close', autospec=True, side_effect=[OSError('close failed'), None])
            as close_pricer,
            patch.object(DummySolarForecaster, 'close', autospec=True) as close_forecaster,
            patch.object(control_loop, 'log_info') as log_info,
            patch.object(control_loop, 'log_error') as log_error,
        ):
            settings_path = Path(directory) / 'settings.json'
            settings_path.write_text(settings.model_dump_json(), encoding='utf-8')

            for run, pool in enumerate(pools, start=1):
                await control_loop.control_loop(settings_path=settings_path, database_write=False)
                self.assertEqual(settings_path.read_bytes(), saved_settings[-1])
                restored = Settings.model_validate_json(saved_settings[-1])
                self.assertEqual(restored.consumers, settings.consumers)
                self.assertEqual(set(runs[-1]), {'charger', 'outlet'})
                self.assertTrue(all(manager._worker.done() for manager in runs[-1].values()))
                self.assertFalse(state.connections.consumers)
                self.assertFalse(state.connections.closing_consumers)
                self.assertNotIn('status/power/consumer/charger/on', registers.get_register_bank())
                self.assertIsNone(state.connections.controller)
                self.assertIsNone(state.connections.pricer)
                self.assertIsNone(state.connections.forecaster)
                self.assertIsNone(state.connections.database_connections)
                self.assertEqual(close_controller.await_count, run)
                self.assertEqual(close_pricer.await_count, run)
                self.assertEqual(close_forecaster.await_count, run)
                pool.begin_close.assert_called_once_with()
                pool.close.assert_awaited_once_with()

            for resource in ('power controller', 'power pricer', 'solar forecaster', 'database pool',
                             "power consumer 'charger'", "power consumer 'outlet'"):
                log_info.assert_any_call(f'Closed {resource} during control-loop shutdown')
            log_error.assert_any_call("Failed to close power pricer during control-loop shutdown: OSError('close failed')")

        self.assertIsNot(runs[0]['charger'], runs[1]['charger'])
        self.assertIsNot(runs[0]['outlet'], runs[1]['outlet'])

    async def test_shutdown_housekeeping_does_not_consume_delegate_budget(self) -> None:
        state = control_loop._ControlState()
        started = asyncio.Event()
        loop = asyncio.get_running_loop()
        original_time = loop.time
        elapsed_housekeeping = 0.0

        def record_info(message: str) -> None:
            if message == 'Starting control-loop shutdown':
                started.set()

        with (
            patch.object(loop, 'time', side_effect=lambda: original_time() + elapsed_housekeeping),
            patch.object(loop, 'slow_callback_duration', 2),
            patch.object(control_loop.Constants, 'MAX_SHUTDOWN_TIMEOUT', timedelta(milliseconds=250)),
            patch.object(control_loop, '_CONTROL_STATE', state),
            patch.object(control_loop, 'log_info', side_effect=record_info),
            patch.object(control_loop, 'log_error') as error,
            patch.object(DummySolarForecaster, 'close', autospec=True) as close_forecaster,
        ):
            await control_loop.connect_forecaster(DummySolarForecasterConnection())
            async with asyncio.timeout(5), asyncio.TaskGroup() as tasks:
                async with state.connections.lock:
                    tasks.create_task(control_loop._shutdown_control_loop(None))
                    await started.wait()
                    elapsed_housekeeping = 1.0

            close_forecaster.assert_awaited_once()
            self.assertIsNone(state.connections.forecaster)
            error.assert_not_called()

    async def test_shutdown_closes_forecaster_while_database_lifecycle_lock_is_held(self) -> None:
        state = control_loop._ControlState()
        pool = create_autospec(SolalaDatabaseConnections, instance=True)
        state.connections.database_connections = pool
        with (
            patch.object(control_loop.Constants, 'MAX_SHUTDOWN_TIMEOUT', timedelta(milliseconds=50)),
            patch.object(control_loop, '_CONTROL_STATE', state),
            patch.object(control_loop, 'log_info') as info,
            patch.object(control_loop, 'log_error') as error,
            patch.object(DummySolarForecaster, 'close', autospec=True) as close_forecaster,
        ):
            await control_loop.connect_forecaster(DummySolarForecasterConnection())
            async with state.database_lifecycle_lock:
                await asyncio.wait_for(control_loop._shutdown_control_loop(None), 1)
            close_forecaster.assert_awaited_once()
            self.assertIsNone(state.connections.forecaster)
            pool.close.assert_not_awaited()
            info.assert_any_call('Closed solar forecaster during control-loop shutdown')
            error.assert_any_call('Still waiting for database pool when control-loop shutdown was interrupted')

    async def test_failed_startup_preserves_saved_settings_until_fallback_succeeds(self) -> None:
        consumers: dict[str, ConsumerConnection] = {'charger': DummyConsumerConnection()}
        saved = Settings(consumers=consumers, forecaster=DummySolarForecasterConnection())
        original = saved.model_dump_json().encode('utf-8')

        for fallback_fails in (False, True):
            with self.subTest(fallback_fails=fallback_fails):
                state = control_loop._ControlState()
                fallback = saved if fallback_fails else Settings(consumers=consumers)
                failed_attempts: list[PowerConsumerManager] = []
                active_attempts: list[PowerConsumerManager] = []
                file_during_failure: list[bytes] = []

                def fail_forecaster(_: DummySolarForecasterConnection) -> DummySolarForecaster:
                    failed_attempts.append(state.connections.consumers['charger'])
                    file_during_failure.append(settings_path.read_bytes())
                    raise OSError('forecaster unavailable')

                async def main_loop() -> None:
                    active_attempts.append(state.connections.consumers['charger'])
                    self.assertTrue(failed_attempts[0]._worker.done())
                    control_loop.exit_control_loop()

                with (
                    tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory,
                    patch.object(control_loop, '_CONTROL_STATE', state),
                    patch.object(control_loop, '_REGISTERS'),
                    patch.object(control_loop, '_control_loop', side_effect=main_loop),
                    patch.object(control_loop, '_connect_dummy_solar_forecaster', side_effect=fail_forecaster),
                    patch.object(control_loop, 'log_info'),
                    patch.object(control_loop, 'log_error'),
                ):
                    settings_path = Path(directory) / 'settings.json'
                    settings_path.write_bytes(original)
                    if fallback_fails:
                        with self.assertRaisesRegex(control_loop.ControlLoopError, 'forecaster'):
                            await control_loop.control_loop(settings_path, fallback, database_write=False)
                        self.assertEqual(settings_path.read_bytes(), original)
                        self.assertFalse(active_attempts)
                        self.assertEqual(len(failed_attempts), 2)
                        self.assertIsNot(failed_attempts[0], failed_attempts[1])
                    else:
                        await control_loop.control_loop(settings_path, fallback, database_write=False)
                        self.assertEqual(len(failed_attempts), 1)
                        self.assertEqual(len(active_attempts), 1)
                        self.assertIsNot(active_attempts[0], failed_attempts[0])
                        persisted = Settings.model_validate_json(settings_path.read_bytes())
                        self.assertEqual(persisted.consumers, consumers)
                        self.assertIsNone(persisted.forecaster)

                self.assertEqual(file_during_failure, [original] * len(failed_attempts))
                self.assertFalse(state.connections.consumers)
                self.assertTrue(all(manager._worker.done() for manager in failed_attempts))

    async def _check_shutdown(self, failure: BaseException | None) -> None:
        state = control_loop._ControlState()
        database_started = asyncio.Event()
        database_finished = asyncio.Event()
        observed = []

        async def database_loop() -> None:
            try:
                database_started.set()
                await asyncio.Event().wait()
            finally:
                observed.append('database cleanup')
                database_finished.set()

        async def main_loop() -> None:
            await database_started.wait()
            if failure is not None:
                raise failure

        with (
            patch.object(control_loop, '_CONTROL_STATE', state),
            patch.object(control_loop, '_REGISTERS'),
            patch.object(control_loop, '_database_loop', side_effect=database_loop),
            patch.object(control_loop, '_control_loop', side_effect=main_loop),
            patch.object(control_loop, 'log_info'),
        ):
            await control_loop.connect_consumer('charger', DummyConsumerConnection())
            worker = state.connections.consumers['charger']._worker
            try:
                await control_loop.control_loop(database_write=False)
            finally:
                self.assertTrue(database_finished.is_set())
                self.assertEqual(observed, ['database cleanup'])
                self.assertTrue(worker.done())
                self.assertFalse(state.connections.consumers)


if __name__ == '__main__':
    unittest.main()
