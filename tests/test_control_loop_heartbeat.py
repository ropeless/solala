import importlib
import unittest
from datetime import timedelta
from unittest.mock import patch

from solala.constants import Constants
from solala.utils.time_extras import now


class ControlLoopHeartbeatTestCase(unittest.TestCase):
    """
    Verify the completion-based heartbeat and overdue timing contract.
    """

    def test_overdue_uses_last_completed_step_not_iteration_start(self):
        control_loop = importlib.import_module('solala.control_loop.control_loop')
        state = control_loop._ControlState()
        current = now()
        state.iteration_start = current - timedelta(seconds=100)
        state.last_control_step = current

        with patch.object(control_loop, '_CONTROL_STATE', state):
            self.assertLess(control_loop.loop_check_overdue(), 1.0)

    def test_overdue_is_measured_after_expected_next_completion(self):
        control_loop = importlib.import_module('solala.control_loop.control_loop')
        state = control_loop._ControlState()
        current = now()
        state.last_control_step = current - Constants.LOOP_TIME - timedelta(seconds=3)

        with patch.object(control_loop, '_CONTROL_STATE', state):
            self.assertAlmostEqual(control_loop.loop_check_overdue(), 3.0, delta=0.5)

    def test_overdue_is_never_negative(self):
        control_loop = importlib.import_module('solala.control_loop.control_loop')
        state = control_loop._ControlState()
        state.last_control_step = now() + timedelta(seconds=30)

        with patch.object(control_loop, '_CONTROL_STATE', state):
            self.assertEqual(control_loop.loop_check_overdue(), 0.0)

    def test_overdue_threshold_precedes_control_duration(self):
        self.assertLess(
            (Constants.LOOP_TIME + Constants.OVERDUE_THRESHOLD).total_seconds(),
            Constants.CONTROL_DURATION,
        )


if __name__ == '__main__':
    unittest.main()
