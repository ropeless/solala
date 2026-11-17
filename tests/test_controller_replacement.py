import importlib
import unittest
from unittest.mock import AsyncMock, patch

from solala.control_loop.modes_and_policies import (
    BatteryMode,
    BatteryPolicy,
    InverterMode,
    InverterPolicy,
)

control_loop = importlib.import_module('solala.control_loop.control_loop')


class ControllerReplacementTestCase(unittest.IsolatedAsyncioTestCase):
    """
    Verify replacement hardware does not inherit previous control intentions.
    """

    async def test_replacement_resets_modes_and_policies(self) -> None:
        state = control_loop._ControlState()
        old_controller = AsyncMock()
        new_controller = AsyncMock()
        old_settings = object()
        new_settings = object()
        state.connections.controller = old_controller
        state.connections.controller_settings = old_settings
        state.control.control_mode.battery_mode = BatteryMode.FORCE_CHARGE
        state.control.control_mode.inverter_mode = InverterMode.ZERO_EXPORT
        state.control.control_mode.battery_policy = BatteryPolicy.CHEAP_CHARGE
        state.control.control_mode.inverter_policy = InverterPolicy.NEG_FEED_IN_ZERO_EXPORT
        state.control.prev_state.controller = old_controller
        state.control.prev_state.control_mode.battery_mode = BatteryMode.FORCE_CHARGE
        state.control.prev_state.control_mode.inverter_mode = InverterMode.ZERO_EXPORT
        state.control.prev_state.control_mode.battery_policy = BatteryPolicy.CHEAP_CHARGE
        state.control.prev_state.control_mode.inverter_policy = InverterPolicy.NEG_FEED_IN_ZERO_EXPORT

        with patch.object(control_loop, '_CONTROL_STATE', state):
            await state.reset_controller(new_controller, new_settings)
            async with control_loop._connections_state():
                await control_loop._control_step(state)

        self.assertIs(state.connections.controller, new_controller)
        self.assertEqual(state.control.control_mode.battery_mode, BatteryMode.UNKNOWN)
        self.assertEqual(state.control.control_mode.inverter_mode, InverterMode.UNKNOWN)
        self.assertEqual(state.control.control_mode.battery_policy, BatteryPolicy.MANUAL)
        self.assertEqual(state.control.control_mode.inverter_policy, InverterPolicy.MANUAL)
        self.assertEqual(state.control.prev_state.control_mode.battery_mode, BatteryMode.UNKNOWN)
        self.assertEqual(state.control.prev_state.control_mode.inverter_mode, InverterMode.UNKNOWN)
        self.assertEqual(state.control.prev_state.control_mode.battery_policy, BatteryPolicy.MANUAL)
        self.assertEqual(state.control.prev_state.control_mode.inverter_policy, InverterPolicy.MANUAL)
        self.assertEqual(state.control.prev_state.battery_commanded_mode, BatteryMode.UNKNOWN)
        self.assertEqual(state.control.prev_state.inverter_commanded_mode, InverterMode.UNKNOWN)
        new_controller.zero_export.assert_not_awaited()
        new_controller.enable_inverter.assert_not_awaited()
        new_controller.disable_inverter.assert_not_awaited()
        new_controller.enable_battery.assert_not_awaited()
        new_controller.force_charge.assert_not_awaited()


if __name__ == '__main__':
    unittest.main()
