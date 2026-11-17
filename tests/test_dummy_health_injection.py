import importlib
import unittest
from unittest.mock import patch

from solala.control_loop.control_health import Severity
from solala.settings import DummyControllerConnection


class DummyHealthInjectionTestCase(unittest.TestCase):
    """
    Verify that simulated issues cannot affect a real controller.
    """

    def setUp(self) -> None:
        self.loop = importlib.import_module('solala.control_loop.control_loop')
        self.state = self.loop._ControlState()
        self.patch_state = patch.object(self.loop, '_CONTROL_STATE', self.state)
        self.patch_state.start()

    def tearDown(self) -> None:
        self.patch_state.stop()

    def test_disabled_by_default(self):
        with patch.dict('os.environ', {}, clear=True):
            self.assertFalse(self.loop.dummy_health_test_enabled())
            with self.assertRaises(RuntimeError):
                self.loop.set_dummy_health_issue(Severity.WARNING)

    def test_real_controller_is_not_eligible(self):
        with patch.dict('os.environ', {'SOLALA_TEST_HEALTH': '1'}):
            self.assertFalse(self.loop.dummy_health_test_enabled())
            with self.assertRaises(RuntimeError):
                self.loop.set_dummy_health_issue(Severity.CAUTION)

    def test_injected_issue_recovers(self):
        self.state.connections.controller_settings = DummyControllerConnection()
        with patch.dict('os.environ', {'SOLALA_TEST_HEALTH': '1'}):
            self.assertTrue(self.loop.dummy_health_test_enabled())
            self.loop.set_dummy_health_issue(Severity.CAUTION)
            self.assertEqual(self.loop.get_control_health()[0], Severity.CAUTION)
            self.loop.set_dummy_health_issue(Severity.WARNING)
            self.assertEqual(self.loop.get_control_health()[0], Severity.WARNING)
            self.loop.set_dummy_health_issue(None)
            self.assertEqual(self.loop.get_control_health()[0], Severity.NORMAL)


if __name__ == '__main__':
    unittest.main()
