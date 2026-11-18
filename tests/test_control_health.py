import importlib
import unittest
from datetime import datetime, timezone
from unittest.mock import patch
from dataclasses import FrozenInstanceError

from solala.control_loop.control_health import ControlHealth, Severity


class ControlHealthTestCase(unittest.TestCase):

    def test_initial_state_is_normal(self):
        health = ControlHealth()
        self.assertEqual(health.severity, Severity.NORMAL)
        self.assertEqual(health.get_issues(), ())

    def test_highest_severity_wins(self):
        health = ControlHealth()
        health.report_failure('consumer', Severity.CAUTION, 'Consumer unavailable')
        health.report_failure('inverter', Severity.WARNING, 'Control unconfirmed')
        self.assertEqual(health.severity, Severity.WARNING)
        self.assertEqual([issue.key for issue in health.get_issues()], ['inverter', 'consumer'])

    def test_repeated_failure_updates_count_without_creating_duplicate(self):
        health = ControlHealth()
        self.assertTrue(health.report_failure('price', Severity.CAUTION, 'Price unavailable'))
        first = health.get_issues()[0]
        self.assertFalse(health.report_failure('price', Severity.CAUTION, 'Price unavailable'))
        updated = health.get_issues()[0]
        self.assertEqual(updated.occurrences, 2)
        self.assertEqual(updated.first_seen, first.first_seen)
        self.assertGreaterEqual(updated.last_seen, first.last_seen)

    def test_change_is_reported(self):
        health = ControlHealth()
        health.report_failure('device', Severity.CAUTION, 'Intermittent')
        self.assertTrue(health.report_failure('device', Severity.WARNING, 'Unsafe'))
        self.assertEqual(health.severity, Severity.WARNING)

    def test_recovery_clears_issue(self):
        health = ControlHealth()
        health.report_failure('device', Severity.WARNING, 'Control failed')
        self.assertTrue(health.report_success('device'))
        self.assertFalse(health.report_success('device'))
        self.assertEqual(health.severity, Severity.NORMAL)
        self.assertEqual(health.get_issues(), ())

    def test_equal_severity_issues_are_ordered_by_time_then_key(self):
        health = ControlHealth()
        with patch('solala.control_loop.control_health.datetime') as clock:
            clock.now.return_value = datetime(2026, 1, 1, tzinfo=timezone.utc)
            health.report_failure('z', Severity.WARNING, 'Z failed')
            health.report_failure('a', Severity.WARNING, 'A failed')
            health.report_failure('c', Severity.CAUTION, 'C failed')
        self.assertEqual([issue.key for issue in health.get_issues()], ['a', 'z', 'c'])

    def test_message_change_updates_issue_without_resetting_occurrences(self):
        health = ControlHealth()
        health.report_failure('device', Severity.CAUTION, 'First failure')
        self.assertTrue(health.report_failure('device', Severity.CAUTION, 'Different failure'))
        issue, = health.get_issues()
        self.assertEqual(issue.message, 'Different failure')
        self.assertEqual(issue.occurrences, 2)

    def test_recovery_only_clears_matching_issue_and_recurrence_starts_new_count(self):
        health = ControlHealth()
        health.report_failure('device', Severity.WARNING, 'Command uncertain')
        health.report_failure('price', Severity.CAUTION, 'Price unavailable')
        self.assertTrue(health.report_success('device'))
        self.assertEqual(health.severity, Severity.CAUTION)
        self.assertEqual([issue.key for issue in health.get_issues()], ['price'])
        health.report_failure('device', Severity.WARNING, 'Command uncertain')
        self.assertEqual(health.get_issues()[0].occurrences, 1)

    def test_snapshot_does_not_change(self):
        health = ControlHealth()
        health.report_failure('device', Severity.CAUTION, 'Unavailable')
        snapshot = health.get_issues()
        health.report_failure('device', Severity.CAUTION, 'Unavailable')
        self.assertEqual(snapshot[0].occurrences, 1)

    def test_invalid_failure_is_rejected(self):
        health = ControlHealth()
        for key, severity, message in [
            ('', Severity.CAUTION, 'Error'),
            ('device', Severity.NORMAL, 'Error'),
            ('device', Severity.CAUTION, ''),
        ]:
            with self.subTest(key=key, severity=severity, message=message):
                with self.assertRaises(ValueError):
                    health.report_failure(key, severity, message)



class ControlHealthAccessTestCase(unittest.TestCase):
    """
    Verify that the GUI-facing health snapshot is independent of later changes.
    """

    def test_snapshot_reports_severity_and_immutable_issues(self):
        control_loop = importlib.import_module('solala.control_loop.control_loop')
        state = control_loop._ControlState()
        state.health.report_failure('consumer', Severity.CAUTION, 'Consumer unavailable')
        state.health.report_failure('inverter_command', Severity.WARNING, 'Command uncertain')

        with patch.object(control_loop, '_CONTROL_STATE', state):
            severity, issues = control_loop.get_control_health()
            self.assertEqual(severity, Severity.WARNING)
            self.assertEqual(tuple(issue.key for issue in issues), ('inverter_command', 'consumer'))

            with self.assertRaises(FrozenInstanceError):
                issues[0].message = 'changed'

            state.health.report_success('inverter_command')
            self.assertEqual(severity, Severity.WARNING)
            self.assertEqual(len(issues), 2)
            new_severity, new_issues = control_loop.get_control_health()
            self.assertEqual(new_severity, Severity.CAUTION)
            self.assertEqual(tuple(issue.key for issue in new_issues), ('consumer',))



class OneShotCommandTestCase(unittest.IsolatedAsyncioTestCase):
    """
    Verify one-shot failure reporting, retry suppression, and recovery.
    """

    async def test_battery_failure_requires_explicit_retry(self):
        from unittest.mock import AsyncMock
        from solala.control_loop.modes_and_policies import BatteryMode, BatteryPolicy

        control_loop = importlib.import_module('solala.control_loop.control_loop')
        state = control_loop._ControlState()
        controller = AsyncMock()
        controller.disable_battery.side_effect = TimeoutError('simulated failure')
        state.connections.controller = controller
        state.control.control_mode.battery_mode = BatteryMode.DISABLE
        state.control.control_mode.battery_policy = BatteryPolicy.MANUAL

        with (
            patch.object(control_loop, '_CONTROL_STATE', state),
            patch.object(control_loop, 'log_exception'),
        ):
            await control_loop._control_step(state)
            self.assertEqual((await control_loop.get_control_mode()).battery_mode, BatteryMode.UNKNOWN)
            self.assertEqual((await control_loop.get_control_mode()).battery_policy, BatteryPolicy.MANUAL)
            self.assertEqual(state.health.severity, Severity.WARNING)
            controller.disable_battery.assert_awaited_once()

            await control_loop._control_step(state)
            controller.disable_battery.assert_awaited_once()
            self.assertEqual(state.health.get_issues()[0].occurrences, 1)

            # A new explicit request may repeat the same failed command.
            state.control.control_mode.battery_mode = BatteryMode.DISABLE
            await control_loop._control_step(state)
            self.assertEqual(controller.disable_battery.await_count, 2)
            self.assertEqual(state.health.get_issues()[0].occurrences, 2)
            self.assertEqual((await control_loop.get_control_mode()).battery_mode, BatteryMode.UNKNOWN)

            state.control.control_mode.battery_mode = BatteryMode.ENABLE
            await control_loop._control_step(state)
            controller.enable_battery.assert_awaited_once()
            self.assertEqual((await control_loop.get_control_mode()).battery_mode, BatteryMode.ENABLE)
            self.assertEqual(state.health.severity, Severity.NORMAL)

    async def test_inverter_enable_failure_reports_unknown_then_recovers(self):
        from unittest.mock import AsyncMock
        from solala.control_loop.modes_and_policies import InverterMode

        control_loop = importlib.import_module('solala.control_loop.control_loop')
        state = control_loop._ControlState()
        controller = AsyncMock()
        controller.enable_inverter.side_effect = TimeoutError('simulated failure')
        state.connections.controller = controller
        state.control.control_mode.inverter_mode = InverterMode.ENABLE

        with (
            patch.object(control_loop, '_CONTROL_STATE', state),
            patch.object(control_loop, 'log_exception'),
        ):
            await control_loop._control_step(state)
            self.assertEqual((await control_loop.get_control_mode()).inverter_mode, InverterMode.UNKNOWN)
            self.assertEqual(state.health.severity, Severity.WARNING)

            await control_loop._control_step(state)
            controller.enable_inverter.assert_awaited_once()

            state.control.control_mode.inverter_mode = InverterMode.DISABLE
            await control_loop._control_step(state)
            self.assertEqual((await control_loop.get_control_mode()).inverter_mode, InverterMode.DISABLE)
            self.assertEqual(state.health.severity, Severity.NORMAL)
            controller.disable_inverter.assert_awaited_once()


if __name__ == '__main__':
    unittest.main()
