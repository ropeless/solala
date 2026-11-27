import asyncio
import unittest
from unittest.mock import AsyncMock, Mock, patch

from solala.control import control_loop
from solala.control.control_health import Severity
from solala.control.control_loop_error import ControlLoopError
from solala.control.power_consumer_manager import PowerConsumerManager
from solala.delegates.power_consumer.consumer_status import ConsumerStatus
from solala.register_bank import RegisterBank
from solala.settings import DummyConsumerConnection


class ConsumerStatusIsolationTestCase(unittest.IsolatedAsyncioTestCase):
    """
    Verify that consumer reporting remains available after individual failures.
    """

    async def asyncSetUp(self) -> None:
        self.state = control_loop._ControlState()
        self.state_patch = patch.object(control_loop, '_CONTROL_STATE', self.state)
        self.state_patch.start()
        self.addCleanup(self.state_patch.stop)

    async def _connect_observed_consumer(self, name: str, delegate: AsyncMock) -> PowerConsumerManager:
        delegate.get_connection_info = Mock(return_value={})
        with (
            patch.object(control_loop, '_connect_dummy_consumer', return_value=delegate),
            patch.object(control_loop, '_REGISTERS'),
            patch.object(control_loop, 'log_info'),
        ):
            await control_loop.connect_consumer(name, DummyConsumerConnection())
        manager = self.state.connections.consumers[name]
        self.addAsyncCleanup(manager.close)
        return manager

    async def test_pending_consumer_does_not_hide_successful_consumer_or_raise_alert(self) -> None:
        """
        Return published statuses while another consumer is waiting for its first value.
        """
        expected = ConsumerStatus(on=True, power=120.0, voltage=240.0, current=0.5, accumulated_energy=None)
        working = Mock(spec=PowerConsumerManager)
        working.try_get_status.return_value = expected
        pending = Mock(spec=PowerConsumerManager)
        pending.try_get_status.return_value = None
        self.state.connections.consumers.update({'working': working, 'pending': pending})

        with patch.object(control_loop, 'log_error') as log_error:
            result = await control_loop.get_consumers_status()

        self.assertEqual(result, {'working': expected})
        working.try_get_status.assert_called_once()
        pending.try_get_status.assert_called_once()
        log_error.assert_not_called()
        self.assertEqual(self.state.health.get_issues(), ())

    async def test_cold_consumer_runs_no_io_until_a_client_requests_it(self) -> None:
        delegate = AsyncMock()
        delegate.get_registers.return_value = RegisterBank({})
        delegate.get_status.return_value = ConsumerStatus(
            on=True, power=120.0, voltage=240.0, current=0.5, accumulated_energy=None,
        )
        manager = PowerConsumerManager(delegate)
        try:
            await asyncio.sleep(0)
            delegate.get_registers.assert_not_awaited()
            delegate.get_status.assert_not_awaited()

            self.assertIsNone(manager.try_get_status())
            self.assertIsNone(manager.discovered_registers)
            manager.request_register_discovery()
            await asyncio.sleep(0)
            self.assertEqual(manager.try_get_status(), delegate.get_status.return_value)
            self.assertIs(manager.discovered_registers, delegate.get_registers.return_value)
            manager.request_register_discovery()
            await asyncio.sleep(0)
            delegate.get_status.assert_awaited_once()
            delegate.get_registers.assert_awaited_once()
        finally:
            await manager.close()

    async def test_consumer_cancellation_propagates(self) -> None:
        """
        Do not interpret cancellation as an ordinary consumer failure.
        """
        cancelled = Mock(spec=PowerConsumerManager)
        cancelled.try_get_status.side_effect = asyncio.CancelledError()
        self.state.connections.consumers['cancelled'] = cancelled

        with self.assertRaises(asyncio.CancelledError):
            await control_loop.get_consumers_status()

    async def test_bank_lookup_observes_discovery_without_requesting_it(self) -> None:
        old_delegate = AsyncMock()
        old_delegate.get_registers.return_value = RegisterBank({'old': 1})
        new_delegate = AsyncMock()
        new_delegate.get_registers.return_value = RegisterBank({'new': 2})
        old = PowerConsumerManager(old_delegate)
        new = PowerConsumerManager(new_delegate)
        registers = control_loop.RegisterManager(
            self.state.control.control_mode, control_loop.get_power_status, control_loop.get_price_now,
        )
        try:
            registers.update_consumers({'meter': old})
            self.state.connections.consumers['meter'] = old
            initial = registers.get_register_bank()
            await asyncio.sleep(0)
            old_delegate.get_registers.assert_not_awaited()
            self.assertIs(registers.get_register_bank(), initial)

            control_loop.request_consumer_register_discovery()
            await asyncio.sleep(0)
            discovered = registers.get_register_bank()
            self.assertIs(discovered['consumer/meter/old'], old_delegate.get_registers.return_value['old'])
            self.assertIs(registers.get_register_bank(), discovered)

            registers.update_consumers({'meter': new})
            self.state.connections.consumers['meter'] = new
            self.assertNotIn('consumer/meter/old', registers.get_register_bank())
            control_loop.request_consumer_register_discovery()
            await asyncio.sleep(0)
            replacement = registers.get_register_bank()
            self.assertIn('consumer/meter/new', replacement)
            self.assertNotIn('consumer/meter/old', replacement)
            self.assertIs(registers.get_register_bank(), replacement)
        finally:
            await asyncio.gather(old.close(), new.close())

    async def test_failed_reads_retry_only_on_new_demand(self) -> None:
        delegate = AsyncMock()
        status = ConsumerStatus(on=False, power=0.0, voltage=240.0, current=0.0, accumulated_energy=None)
        bank = RegisterBank({})
        delegate.get_status.side_effect = [ConnectionError('offline'), status]
        delegate.get_registers.side_effect = [ConnectionError('offline'), bank]
        manager = PowerConsumerManager(delegate)
        try:
            self.assertIsNone(manager.try_get_status())
            manager.request_register_discovery()
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            delegate.get_status.assert_awaited_once()
            delegate.get_registers.assert_awaited_once()
            self.assertIsNone(manager.try_get_status())
            self.assertIsNone(manager.discovered_registers)
            manager.request_register_discovery()
            await asyncio.sleep(0)
            self.assertEqual(manager.try_get_status(), status)
            self.assertIs(manager.discovered_registers, bank)
        finally:
            await manager.close()

    async def test_consumer_failure_repetition_and_recovery(self) -> None:
        """
        Count completed attempts and log the first failure and subsequent recovery.
        """
        expected = ConsumerStatus(on=True, power=120.0, voltage=240.0, current=0.5, accumulated_energy=None)
        started = asyncio.Event()
        release = asyncio.Event()
        consumer = AsyncMock()

        async def slow_failure() -> ConsumerStatus:
            started.set()
            await release.wait()
            raise ConnectionError('offline')

        consumer.get_status.side_effect = slow_failure
        await self._connect_observed_consumer('meter', consumer)

        with (
            patch.object(control_loop, 'log_error') as log_error,
            patch.object(control_loop, 'log_info') as log_info,
        ):
            try:
                self.assertEqual(await control_loop.get_consumers_status(), {})
                await asyncio.wait_for(started.wait(), 1)
                for _ in range(3):
                    self.assertEqual(await control_loop.get_consumers_status(), {})
                self.assertEqual(self.state.health.get_issues(), ())
                log_error.assert_not_called()
            finally:
                release.set()
            await asyncio.sleep(0)
            issues = self.state.health.get_issues()
            self.assertEqual(len(issues), 1)
            self.assertEqual(issues[0].key, 'consumer_status:meter')
            self.assertEqual(issues[0].severity, Severity.CAUTION)
            self.assertEqual(issues[0].occurrences, 1)
            log_error.assert_called_once_with("Consumer 'meter' status unavailable: ConnectionError('offline')")

            for _ in range(3):
                self.assertEqual(await control_loop.get_consumers_status(), {})
            self.assertEqual(self.state.health.get_issues()[0].occurrences, 1)
            await asyncio.sleep(0)
            self.assertEqual(self.state.health.get_issues()[0].occurrences, 2)
            log_error.assert_called_once()

            consumer.get_status.side_effect = None
            consumer.get_status.return_value = expected
            self.assertEqual(await control_loop.get_consumers_status(), {})
            await asyncio.sleep(0)
            self.assertEqual(await control_loop.get_consumers_status(), {'meter': expected})
            self.assertEqual(self.state.health.get_issues(), ())
            log_info.assert_called_once_with("Consumer 'meter' status recovered")

    async def test_removed_consumer_clears_reporting_issue(self) -> None:
        """
        Removing a consumer must not leave an obsolete health issue.
        """
        consumer = AsyncMock()
        consumer.get_status.side_effect = ConnectionError('offline')
        consumer.get_registers.side_effect = ConnectionError('discovery failed')
        await self._connect_observed_consumer('meter', consumer)

        with (
            patch.object(control_loop, 'log_error') as log_error,
            patch.object(control_loop, 'log_info') as log_info,
        ):
            await control_loop.get_consumers_status()
            control_loop.request_consumer_register_discovery()
            await asyncio.sleep(0)
            self.assertEqual(
                {issue.key for issue in self.state.health.get_issues()},
                {'consumer_status:meter', 'consumer_registers:meter'},
            )
            log_error.assert_any_call("Consumer 'meter' registers unavailable: ConnectionError('discovery failed')")

            consumer.get_registers.side_effect = [RegisterBank({})]
            control_loop.request_consumer_register_discovery()
            await asyncio.sleep(0)
            self.assertEqual([issue.key for issue in self.state.health.get_issues()], ['consumer_status:meter'])
            log_info.assert_called_once_with("Consumer 'meter' registers recovered")

            with patch.object(control_loop, '_REGISTERS'):
                await control_loop.disconnect_consumer('meter')
        self.assertEqual(self.state.health.get_issues(), ())

    async def test_stalled_read_leaves_control_step_and_other_consumer_available(self) -> None:
        started = asyncio.Event()
        release = asyncio.Event()
        expected = ConsumerStatus(on=False, power=0.0, voltage=240.0, current=0.0, accumulated_energy=None)

        async def stalled_status() -> ConsumerStatus:
            started.set()
            await release.wait()
            return expected

        stalled = AsyncMock()
        stalled.get_status.side_effect = stalled_status
        healthy = AsyncMock()
        healthy.get_status.return_value = expected
        healthy.get_registers.return_value = RegisterBank({'voltage': 240.0})
        stalled_manager = PowerConsumerManager(stalled)
        healthy_manager = PowerConsumerManager(healthy)
        self.state.connections.consumers.update({'stalled': stalled_manager, 'healthy': healthy_manager})
        with patch.object(control_loop, 'log_error'), patch.object(control_loop, 'log_info'):
            try:
                self.assertEqual(await control_loop.get_consumers_status(), {})
                await asyncio.wait_for(started.wait(), 1)
                self.assertIsNone(healthy_manager.discovered_registers)
                healthy_manager.request_register_discovery()
                await asyncio.sleep(0)
                async with asyncio.timeout(1):
                    async with control_loop._connections_state():
                        await control_loop._control_step(self.state)
                    self.assertEqual(await control_loop.get_consumers_status(), {'healthy': expected})
                self.assertIs(healthy_manager.discovered_registers, healthy.get_registers.return_value)
                stalled.get_status.assert_awaited_once()
            finally:
                release.set()
                await asyncio.gather(stalled_manager.close(), healthy_manager.close())
        stalled.close.assert_awaited_once()
        healthy.close.assert_awaited_once()

    async def test_consumer_name_can_be_reused_after_stalled_disconnect_completes(self) -> None:
        started = asyncio.Event()
        release = asyncio.Event()
        closing = asyncio.Event()
        config = DummyConsumerConnection()

        async def stalled_status() -> ConsumerStatus:
            started.set()
            await release.wait()
            raise ConnectionError('late failure from retired consumer')

        old_delegate = AsyncMock()
        old_delegate.get_status.side_effect = stalled_status
        new_delegate = AsyncMock()
        new_delegate.get_connection_info = Mock(return_value={})
        old_manager = await self._connect_observed_consumer('meter', old_delegate)
        close_old = old_manager.close

        async def observe_close() -> None:
            closing.set()
            await close_old()

        with (
            patch.object(old_manager, 'close', side_effect=observe_close),
            patch.object(control_loop, '_connect_dummy_consumer', return_value=new_delegate) as factory,
            patch.object(control_loop, '_REGISTERS'),
            patch.object(control_loop, 'log_info') as info_log,
            patch.object(control_loop, 'log_error') as error_log,
        ):
            self.assertIsNone(old_manager.try_get_status())
            await asyncio.wait_for(started.wait(), 1)
            retirement = asyncio.create_task(control_loop.disconnect_consumer('meter'))
            concurrent_disconnect = asyncio.create_task(control_loop.disconnect_consumer('meter'))
            try:
                try:
                    await asyncio.wait_for(closing.wait(), 1)
                    async with asyncio.timeout(0.25):
                        async with control_loop._connections_state():
                            await control_loop._control_step(self.state)
                            self.assertNotIn('meter', self.state.connections.consumers)
                        with self.assertRaisesRegex(ControlLoopError, 'consumer name .* in use'):
                            await control_loop.connect_consumer('meter', config)
                    self.assertFalse(retirement.done())
                    self.assertFalse(concurrent_disconnect.done())
                    old_delegate.close.assert_not_awaited()
                    factory.assert_not_called()
                finally:
                    release.set()
                    await asyncio.wait_for(asyncio.gather(retirement, concurrent_disconnect), 1)
                old_delegate.close.assert_awaited_once()
                self.assertEqual(self.state.health.get_issues(), ())
                self.assertEqual(
                    [call.args[0] for call in info_log.call_args_list],
                    ["Power consumer 'meter' disconnected"] * 2,
                )
                await control_loop.connect_consumer('meter', config)
                replacement = self.state.connections.consumers['meter']
                self.assertIsNot(replacement, old_manager)
                self.assertIsNone(replacement.try_get_status())
                await asyncio.sleep(0)
                new_delegate.get_status.assert_awaited_once()
                with self.assertRaisesRegex(ControlLoopError, 'consumer name .* in use'):
                    await control_loop.connect_consumer('meter', config)
                self.assertIs(self.state.connections.consumers['meter'], replacement)
                factory.assert_called_once()
                info_log.assert_called_with("Power consumer 'meter' connection: {}")
                self.assertEqual(error_log.call_count, 2)
            finally:
                await control_loop.disconnect_consumer('meter')

    async def test_connect_failure_leaves_consumer_unregistered(self) -> None:
        config = DummyConsumerConnection()
        for failure_at in ('connection_info', 'registers'):
            with self.subTest(failure_at=failure_at):
                delegate = AsyncMock()
                info = Mock(return_value={})
                delegate.get_connection_info = info
                update = Mock()
                if failure_at == 'connection_info':
                    info.side_effect = RuntimeError('connection info failed')
                else:
                    update.side_effect = RuntimeError('register update failed')
                with (
                    patch.object(control_loop, '_connect_dummy_consumer', return_value=delegate),
                    patch.object(control_loop, '_REGISTERS', Mock(update_consumers=update)),
                    patch.object(control_loop, 'log_error') as error_log,
                ):
                    try:
                        with self.assertRaises(ControlLoopError):
                            await control_loop.connect_consumer('meter', config)
                        self.assertNotIn('meter', self.state.connections.consumers)
                        self.assertNotIn('meter', self.state.connections.consumers_settings)
                        delegate.close.assert_awaited_once()
                        if failure_at == 'registers':
                            prepared = update.call_args.args[0]['meter']
                            self.assertTrue(prepared._worker.done())
                        error_log.assert_called_once()
                        self.assertIn("could not connect power consumer 'meter'", error_log.call_args.args[0])
                    finally:
                        manager = self.state.connections.consumers.get('meter')
                        if manager is not None:
                            await manager.close()
                            self.state.reset_consumer('meter', None, None)

    async def test_disconnect_logs_already_disconnected_and_failed_close(self) -> None:
        with patch.object(control_loop, 'log_info') as info_log:
            await control_loop.disconnect_consumer('meter')
        info_log.assert_called_once_with("Power consumer 'meter' is already disconnected")

        delegate = AsyncMock()
        delegate.close.side_effect = RuntimeError('close failed')
        self.state.reset_consumer('meter', PowerConsumerManager(delegate), DummyConsumerConnection())
        with (
            patch.object(control_loop, '_REGISTERS'),
            patch.object(control_loop, 'log_error') as error_log,
        ):
            with self.assertRaisesRegex(ControlLoopError, 'could not disconnect') as failure:
                await control_loop.disconnect_consumer('meter')
        self.assertIsInstance(failure.exception.__cause__, RuntimeError)
        error_log.assert_called_once()
        self.assertIn("could not disconnect power consumer 'meter'", error_log.call_args.args[0])
