import asyncio
import importlib
import unittest
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

from solala.control.control_health import Severity

control_loop = importlib.import_module('solala.control.control_loop')


class DatabaseHealthTestCase(unittest.IsolatedAsyncioTestCase):
    """
    Verify database measurement health across successive logging cycles.
    """

    async def test_failure_repetition_and_recovery(self) -> None:
        """
        Retain repeated failures and clear the issue only after a successful write.
        """
        state = control_loop._ControlState()
        outcomes = iter((ConnectionError('offline'), ConnectionError('offline'), None))
        snapshots = []

        @asynccontextmanager
        async def database():
            yield object()

        async def insert_measurement(*args):
            outcome = next(outcomes)
            if outcome is not None:
                raise outcome

        async def sleep(*args):
            snapshots.append(state.health.get_issues())
            if len(snapshots) == 3:
                state.control_loop_running = False

        with (
            patch.object(control_loop, '_CONTROL_STATE', state),
            patch.object(control_loop, '_database', database),
            patch.object(control_loop, '_insert_measurement', side_effect=insert_measurement),
            patch.object(control_loop, '_update_listeners'),
            patch.object(control_loop, 'log_exception') as log_exception,
            patch.object(control_loop, 'log_info') as log_info,
            patch.object(control_loop.asyncio, 'sleep', side_effect=sleep),
        ):
            await control_loop._database_loop()

        self.assertEqual(len(snapshots[0]), 1)
        self.assertEqual(snapshots[0][0].key, 'database_measurement')
        self.assertEqual(snapshots[0][0].severity, Severity.CAUTION)
        self.assertEqual(snapshots[0][0].occurrences, 1)
        self.assertEqual(snapshots[1][0].occurrences, 2)
        self.assertEqual(snapshots[2], ())
        log_exception.assert_called_once_with('Database measurement failed')
        self.assertTrue(any('recovered' in call.args[0] for call in log_info.call_args_list))

    async def test_disabled_logging_does_not_clear_failure(self) -> None:
        """
        Skipping database writes does not demonstrate recovery.
        """
        state = control_loop._ControlState()
        state.database_write = False
        state.health.report_failure('database_measurement', Severity.CAUTION, 'Database measurement could not be saved')

        async def sleep(*args):
            state.control_loop_running = False

        with (
            patch.object(control_loop, '_CONTROL_STATE', state),
            patch.object(control_loop, '_insert_measurement', new_callable=AsyncMock) as insert,
            patch.object(control_loop, '_update_listeners'),
            patch.object(control_loop.asyncio, 'sleep', side_effect=sleep),
        ):
            await control_loop._database_loop()

        insert.assert_not_awaited()
        self.assertEqual(state.health.get_issues()[0].key, 'database_measurement')
