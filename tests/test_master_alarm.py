import unittest
from unittest.mock import patch

from solala.constants import Constants
from solala.control_loop.control_health import Severity
from solala.server.master_alarm import _alarm_state


class MasterAlarmStateTestCase(unittest.TestCase):
    """
    Verify server-confirmed alarm precedence and overdue hysteresis.
    """

    def _state(self, severity: Severity, overdue: float, previous: str = 'LIVE') -> str:
        with (
            patch('solala.server.master_alarm.control_loop.get_control_health',
                  return_value=(severity, ())),
            patch('solala.server.master_alarm.control_loop.loop_check_overdue',
                  return_value=overdue),
        ):
            state, _ = _alarm_state(previous)
        return state

    def test_operational_health_levels(self):
        for severity in Severity:
            with self.subTest(severity=severity):
                self.assertEqual(self._state(severity, 0), severity.name)

    def test_stalled_overrides_warning(self):
        threshold = Constants.OVERDUE_THRESHOLD.total_seconds()
        self.assertEqual(self._state(Severity.WARNING, threshold + 0.01), 'STALLED')

    def test_intermediate_overdue_preserves_stalled(self):
        self.assertEqual(self._state(Severity.LIVE, 1, 'STALLED'), 'STALLED')

    def test_intermediate_overdue_preserves_operational_health(self):
        self.assertEqual(self._state(Severity.CAUTION, 1, 'LIVE'), 'CAUTION')

    def test_stalled_recovers_on_fresh_heartbeat(self):
        self.assertEqual(self._state(Severity.CAUTION, 0, 'STALLED'), 'CAUTION')

    def test_threshold_boundary_is_not_stalled(self):
        threshold = Constants.OVERDUE_THRESHOLD.total_seconds()
        self.assertEqual(self._state(Severity.LIVE, threshold), 'LIVE')


if __name__ == '__main__':
    unittest.main()
