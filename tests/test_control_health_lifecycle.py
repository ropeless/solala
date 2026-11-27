import importlib
import unittest
from unittest.mock import patch

from solala.control.control_health import Severity

control_loop = importlib.import_module('solala.control.control_loop')


class ControlHealthLifecycleTestCase(unittest.IsolatedAsyncioTestCase):
    """
    Protect unresolved command uncertainty across controller lifecycle changes.
    """

    async def asyncSetUp(self) -> None:
        self.state = control_loop._ControlState()
        self.patch_state = patch.object(control_loop, '_CONTROL_STATE', self.state)
        self.patch_state.start()
        self.addCleanup(self.patch_state.stop)

    async def test_disconnect_preserves_uncertain_commands(self) -> None:
        """
        Disconnecting does not establish the hardware's actual state.
        """
        self.state.health.report_failure(
            'battery_command', Severity.WARNING, 'Battery command outcome is uncertain')
        self.state.health.report_failure(
            'inverter_command', Severity.WARNING, 'Inverter command outcome is uncertain')

        await self.state.reset_controller(None, None)
        control_loop._check_power_controller(self.state, self.state.control.prev_state)

        self.assertEqual(
            {issue.key for issue in self.state.health.get_issues()},
            {'battery_command', 'inverter_command'},
        )
        self.assertEqual(self.state.health.severity, Severity.WARNING)

    async def test_controller_replacement_preserves_uncertain_commands(self) -> None:
        """
        Replacing a controller does not confirm an earlier command's outcome.
        """
        self.state.health.report_failure(
            'inverter_command', Severity.WARNING, 'Inverter command outcome is uncertain')
        first_controller = object()
        second_controller = object()

        self.state.connections.controller = first_controller
        control_loop._check_power_controller(self.state, self.state.control.prev_state)
        self.state.connections.controller = second_controller
        control_loop._check_power_controller(self.state, self.state.control.prev_state)

        self.assertIs(self.state.control.prev_state.controller, second_controller)
        self.assertEqual(
            tuple(issue.key for issue in self.state.health.get_issues()),
            ('inverter_command',),
        )

    def test_unrelated_success_does_not_clear_command_uncertainty(self) -> None:
        """
        Successful reporting cannot clear an unresolved hardware command.
        """
        self.state.health.report_failure(
            'battery_command', Severity.WARNING, 'Battery command outcome is uncertain')
        self.state.health.report_failure(
            'database_measurement', Severity.CAUTION, 'Database measurement could not be saved')

        self.assertTrue(self.state.health.report_success('database_measurement'))
        self.assertFalse(self.state.health.report_success('control_step'))

        self.assertEqual(
            tuple(issue.key for issue in self.state.health.get_issues()),
            ('battery_command',),
        )
        self.assertEqual(self.state.health.severity, Severity.WARNING)
