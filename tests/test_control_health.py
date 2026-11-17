import unittest

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


if __name__ == '__main__':
    unittest.main()
