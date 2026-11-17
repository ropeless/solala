import asyncio
import importlib
import unittest
from unittest.mock import AsyncMock, patch

from solala.delegates.power_consumer.consumer_status import ConsumerStatus

control_loop = importlib.import_module('solala.control_loop.control_loop')


class ConsumerStatusIsolationTestCase(unittest.IsolatedAsyncioTestCase):
    """
    Verify that consumer reporting remains available after individual failures.
    """

    async def asyncSetUp(self) -> None:
        self.state = control_loop._ControlState()
        self.state_patch = patch.object(control_loop, '_CONTROL_STATE', self.state)
        self.state_patch.start()
        self.addCleanup(self.state_patch.stop)

    async def test_failed_consumer_does_not_hide_successful_consumer(self) -> None:
        """
        Return successful statuses and omit a consumer whose request fails.
        """
        expected = ConsumerStatus(on=True, power=120.0, voltage=240.0, current=0.5)
        working = AsyncMock()
        working.get_status.return_value = expected
        failing = AsyncMock()
        failing.get_status.side_effect = ConnectionError('offline')
        self.state.connections.consumers.update({'working': working, 'failing': failing})

        with patch.object(control_loop, 'log_error') as log_error:
            result = await control_loop.get_consumers_status()

        self.assertEqual(result, {'working': expected})
        working.get_status.assert_awaited_once()
        failing.get_status.assert_awaited_once()
        log_error.assert_called_once()
        self.assertIn('failing', log_error.call_args.args[0])

    async def test_consumer_cancellation_propagates(self) -> None:
        """
        Do not interpret cancellation as an ordinary consumer failure.
        """
        cancelled = AsyncMock()
        cancelled.get_status.side_effect = asyncio.CancelledError()
        self.state.connections.consumers['cancelled'] = cancelled

        with self.assertRaises(asyncio.CancelledError):
            await control_loop.get_consumers_status()
