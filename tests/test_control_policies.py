import importlib
import unittest
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

from solala.constants import Constants
from solala.control_loop.modes_and_policies import BatteryMode, BatteryPolicy, InverterMode, InverterPolicy
from solala.delegates.power_pricer.price import Price

control_loop = importlib.import_module('solala.control_loop.control_loop')


class ControlPolicyTestCase(unittest.IsolatedAsyncioTestCase):
    """
    Exercise policy decisions through the real control step without hardware.
    """

    async def asyncSetUp(self) -> None:
        self.state = control_loop._ControlState()
        self.controller = AsyncMock()
        self.state.connections.controller = self.controller
        self.state.connections.pricer = AsyncMock()
        self.state.control.prev_state.controller = self.controller
        self.state.control.prev_state.control_mode.battery_mode = BatteryMode.ENABLE
        self.state.control.prev_state.control_mode.inverter_mode = InverterMode.ENABLE
        self.state.control.control_mode.battery_mode = BatteryMode.ENABLE
        self.state.control.control_mode.inverter_mode = InverterMode.ENABLE
        self.state.control.control_mode.start_charge_price_threshold = 10
        self.state.control.control_mode.stop_charge_price_threshold = 20
        self.state.control.control_mode.disable_export_price_threshold = -5
        self.state.control.control_mode.enable_export_price_threshold = 5
        self.state_patch = patch.object(control_loop, '_CONTROL_STATE', self.state)
        self.state_patch.start()
        self.addCleanup(self.state_patch.stop)
        self.price_mock = AsyncMock()
        self.price_patch = patch.object(control_loop, 'get_price_now', self.price_mock)
        self.price_patch.start()
        self.addCleanup(self.price_patch.stop)

    async def step(self, buy: float, feed_in: float) -> None:
        start = datetime(2026, 1, 1, tzinfo=UTC)
        self.price_mock.return_value = Price(
            start_time=start,
            end_time=start + timedelta(minutes=30),
            renewables=50,
            buy_price=buy,
            feed_in_price=feed_in,
            is_estimate=False,
        )
        async with control_loop._connections_state():
            await control_loop._control_step(self.state)

    async def test_disconnected_controller_acknowledges_control_change(self) -> None:
        """
        A pending change must not cause a busy loop without a controller.
        """
        self.state.connections.controller = None
        self.state.control_changed.set()

        async with control_loop._connections_state():
            await control_loop._control_step(self.state)

        self.assertFalse(self.state.control_changed.is_set())
        self.assertIsNone(self.state.control.prev_state.controller)
        self.price_mock.assert_not_awaited()

    async def test_battery_charge_hysteresis_and_boundaries(self) -> None:
        self.state.control.control_mode.battery_policy = BatteryPolicy.CHEAP_CHARGE
        for price, expected in [
            (10, BatteryMode.ENABLE),
            (9, BatteryMode.FORCE_CHARGE),
            (10, BatteryMode.FORCE_CHARGE),
            (15, BatteryMode.FORCE_CHARGE),
            (20, BatteryMode.FORCE_CHARGE),
            (21, BatteryMode.ENABLE),
            (15, BatteryMode.ENABLE),
        ]:
            with self.subTest(buy_price=price):
                await self.step(price, 100)
                self.assertEqual(self.state.control.prev_state.control_mode.battery_mode, expected)
        self.assertEqual(self.controller.force_charge.await_count, 1)
        self.assertEqual(self.controller.enable_battery.await_count, 1)

    async def test_inverter_export_hysteresis_and_boundaries(self) -> None:
        self.state.control.control_mode.inverter_policy = InverterPolicy.NEG_FEED_IN_ZERO_EXPORT
        for price, expected in [
            (-5, InverterMode.ENABLE),
            (-6, InverterMode.ZERO_EXPORT),
            (-5, InverterMode.ZERO_EXPORT),
            (0, InverterMode.ZERO_EXPORT),
            (5, InverterMode.ZERO_EXPORT),
            (6, InverterMode.ENABLE),
            (0, InverterMode.ENABLE),
        ]:
            with self.subTest(feed_in_price=price):
                await self.step(100, price)
                self.assertEqual(self.state.control.prev_state.control_mode.inverter_mode, expected)
        self.assertEqual(self.controller.zero_export.await_count, 4)
        self.assertEqual(self.controller.enable_inverter.await_count, 1)
        self.controller.zero_export.assert_any_await(change_duration=Constants.CONTROL_DURATION)

    async def test_manual_modes_ignore_prices(self) -> None:
        self.state.control.control_mode.battery_mode = BatteryMode.DISABLE
        self.state.control.control_mode.inverter_mode = InverterMode.ZERO_EXPORT
        await self.step(-100, -100)
        self.assertEqual(self.state.control.control_mode.battery_mode, BatteryMode.DISABLE)
        self.assertEqual(self.state.control.control_mode.inverter_mode, InverterMode.ZERO_EXPORT)
        self.price_mock.assert_not_awaited()
        self.controller.disable_battery.assert_awaited_once()
        self.controller.zero_export.assert_awaited_once_with(change_duration=Constants.CONTROL_DURATION)

    async def test_missing_pricer_does_not_change_automatic_modes(self) -> None:
        self.state.control.control_mode.battery_policy = BatteryPolicy.CHEAP_CHARGE
        self.state.control.control_mode.inverter_policy = InverterPolicy.NEG_FEED_IN_ZERO_EXPORT
        self.state.connections.pricer = None
        await self.step(-100, -100)
        self.assertEqual(self.state.control.control_mode.battery_mode, BatteryMode.ENABLE)
        self.assertEqual(self.state.control.control_mode.inverter_mode, InverterMode.ENABLE)
        self.price_mock.assert_not_awaited()
        self.controller.force_charge.assert_not_awaited()
        self.controller.zero_export.assert_not_awaited()

    async def test_both_automatic_policies_fetch_cached_price(self) -> None:
        self.state.control.control_mode.battery_policy = BatteryPolicy.CHEAP_CHARGE
        self.state.control.control_mode.inverter_policy = InverterPolicy.NEG_FEED_IN_ZERO_EXPORT
        await self.step(9, -6)
        self.assertEqual(self.price_mock.await_count, 2)
        self.controller.force_charge.assert_awaited_once()
        self.controller.zero_export.assert_awaited_once_with(change_duration=Constants.CONTROL_DURATION)


    async def test_inverter_price_failure_preserves_zero_export_keep_alive(self) -> None:
        """
        A failed price lookup must not suppress the active zero-export keep-alive.
        """
        self.state.control.control_mode.inverter_policy = InverterPolicy.NEG_FEED_IN_ZERO_EXPORT
        self.state.control.control_mode.inverter_mode = InverterMode.ENABLE
        self.state.control.prev_state.control_mode.inverter_policy = InverterPolicy.NEG_FEED_IN_ZERO_EXPORT
        self.state.control.prev_state.control_mode.inverter_mode = InverterMode.ZERO_EXPORT
        self.price_mock.side_effect = RuntimeError('price lookup failed')

        async with control_loop._connections_state():
            await control_loop._control_step(self.state)

        self.controller.zero_export.assert_awaited_once_with(
            change_duration=Constants.CONTROL_DURATION
        )
        self.controller.enable_inverter.assert_not_awaited()
        self.assertEqual(
            self.state.control.prev_state.control_mode.inverter_mode,
            InverterMode.ZERO_EXPORT,
        )

    async def test_failed_zero_export_is_logged_and_retried(self) -> None:
        self.state.control.control_mode.inverter_mode = InverterMode.ZERO_EXPORT
        self.controller.zero_export.side_effect = [RuntimeError('command failed'), None]

        with patch.object(control_loop.LOGGER, 'exception') as log_exception:
            await self.step(100, 100)
            self.assertEqual(self.state.control.prev_state.control_mode.inverter_mode, InverterMode.ZERO_EXPORT)
            self.assertEqual(self.state.control.prev_state.inverter_commanded_mode, InverterMode.UNKNOWN)
            self.assertEqual(self.state.health.severity, control_loop.Severity.WARNING)
            await self.step(100, 100)

        self.assertEqual(self.controller.zero_export.await_count, 2)
        self.controller.zero_export.assert_awaited_with(change_duration=Constants.CONTROL_DURATION)
        log_exception.assert_called_once()
        self.assertEqual(self.state.health.severity, control_loop.Severity.NORMAL)
        self.assertEqual(self.state.control.prev_state.inverter_commanded_mode, InverterMode.ZERO_EXPORT)

    async def test_failed_disable_inverter_is_logged_and_retried(self) -> None:
        self.state.control.control_mode.inverter_mode = InverterMode.DISABLE
        self.controller.disable_inverter.side_effect = [RuntimeError('command failed'), None]

        with patch.object(control_loop.LOGGER, 'exception') as log_exception:
            await self.step(100, 100)
            self.assertEqual(self.state.control.prev_state.control_mode.inverter_mode, InverterMode.DISABLE)
            self.assertEqual(self.state.control.prev_state.inverter_commanded_mode, InverterMode.UNKNOWN)
            self.assertEqual(self.state.health.severity, control_loop.Severity.WARNING)
            await self.step(100, 100)

        self.assertEqual(self.controller.disable_inverter.await_count, 2)
        self.controller.disable_inverter.assert_awaited_with(change_duration=Constants.CONTROL_DURATION)
        log_exception.assert_called_once()
        self.assertEqual(self.state.health.severity, control_loop.Severity.NORMAL)
        self.assertEqual(self.state.control.prev_state.inverter_commanded_mode, InverterMode.DISABLE)


if __name__ == '__main__':
    unittest.main()
