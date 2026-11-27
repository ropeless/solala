import unittest
from dataclasses import replace
from unittest.mock import AsyncMock, patch

from solala.control import control_loop
from solala.control.control_health import Severity


class PowerStatusHealthTestCase(unittest.IsolatedAsyncioTestCase):
    """
    Verify unavailable readings never masquerade as current power measurements.
    """

    async def asyncSetUp(self) -> None:
        self.state = control_loop._ControlState()
        self.controller = AsyncMock()
        self.state.connections.controller = self.controller
        self.state_patch = patch.object(control_loop, '_CONTROL_STATE', self.state)
        self.state_patch.start()
        self.addCleanup(self.state_patch.stop)

    async def test_failure_discards_previous_reading_and_recovery_requires_read(self) -> None:
        measured = replace(control_loop._NO_POWER, solar_power=123)
        self.controller.get_status.return_value = measured
        self.assertEqual(await control_loop.get_power_status(), measured)
        self.assertEqual(self.state.health.get_issues(), ())

        self.state.cache.last_power_valid = False
        self.controller.get_status.side_effect = OSError('unavailable')
        with patch.object(control_loop, 'log_exception'):
            self.assertEqual(await control_loop.get_power_status(), control_loop._NO_POWER)
        self.assertFalse(self.state.cache.last_power_valid)
        issues = self.state.health.get_issues()
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].key, 'power_status')
        self.assertEqual(issues[0].severity, Severity.CAUTION)

        self.controller.get_status.side_effect = None
        self.controller.get_status.return_value = measured
        self.assertEqual(await control_loop.get_power_status(), measured)
        self.assertTrue(self.state.cache.last_power_valid)
        self.assertEqual(self.state.health.get_issues(), ())

    async def test_disconnection_invalidates_cached_measurement(self) -> None:
        measured = replace(control_loop._NO_POWER, solar_power=123)
        self.state.cache.last_power = measured
        self.state.cache.last_power_valid = True
        with patch.object(control_loop, 'log_error'):
            await self.state.reset_controller(None, None)
            self.assertEqual(await control_loop.get_power_status(), control_loop._NO_POWER)
        self.assertFalse(self.state.cache.last_power_valid)
        self.assertEqual(self.state.health.get_issues()[0].key, 'power_status')
        self.controller.get_status.assert_not_awaited()


if __name__ == '__main__':
    unittest.main()
