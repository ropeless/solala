import unittest
from unittest.mock import AsyncMock, patch

from pydantic import ValidationError

from solala.delegates.power_consumer.dummy_power_consumer.dummy_power_consumer import (
    DummyPowerConsumer, FailureLocation,
)
from solala.settings import DummyConsumerConnection, DummyConsumerFailure


class DummyConsumerFailureTestCase(unittest.IsolatedAsyncioTestCase):
    """
    Verify simulated consumer faults and settings serialization.
    """

    async def test_no_failure(self) -> None:
        consumer = DummyPowerConsumer()
        await consumer.get_status()
        await consumer.get_registers()
        consumer.get_connection_info()

    async def test_get_status_exception(self) -> None:
        consumer = DummyPowerConsumer(
            failure=DummyConsumerFailure(
                location=FailureLocation.get_status,
                exception=TimeoutError('simulated'),
            ),
        )
        with self.assertRaisesRegex(TimeoutError, 'simulated'):
            await consumer.get_status()
        await consumer.get_registers()

    async def test_get_registers_exception(self) -> None:
        consumer = DummyPowerConsumer(
            failure=DummyConsumerFailure(
                location=FailureLocation.get_registers,
                exception=ConnectionError('simulated'),
            ),
        )
        with self.assertRaises(ConnectionError):
            await consumer.get_registers()

    async def test_get_connection_info_exception(self) -> None:
        consumer = DummyPowerConsumer(
            failure=DummyConsumerFailure(
                location=FailureLocation.get_connection_info,
                exception=RuntimeError('simulated'),
            ),
        )
        with self.assertRaisesRegex(RuntimeError, 'simulated'):
            consumer.get_connection_info()

    async def test_async_delay(self) -> None:
        consumer = DummyPowerConsumer(
            failure=DummyConsumerFailure(
                location=FailureLocation.get_status,
                sleep=1.5,
            ),
        )
        with patch('solala.utils.dummy_failure.asyncio.sleep', new_callable=AsyncMock) as sleep:
            await consumer.get_status()
        sleep.assert_awaited_once_with(1.5)

    async def test_probability(self) -> None:
        consumer = DummyPowerConsumer(
            failure=DummyConsumerFailure(
                location=FailureLocation.get_status,
                probability=0.5,
                exception=RuntimeError('simulated'),
            ),
        )
        with patch('solala.utils.dummy_failure.random.random', return_value=0.8):
            await consumer.get_status()
        with patch('solala.utils.dummy_failure.random.random', return_value=0.2):
            with self.assertRaises(RuntimeError):
                await consumer.get_status()

    async def test_settings_round_trip(self) -> None:
        settings = DummyConsumerConnection(
            failure=DummyConsumerFailure(
                location=FailureLocation.get_status,
                probability=0.25,
                exception=TimeoutError('simulated'),
            ),
        )
        restored = DummyConsumerConnection.model_validate_json(settings.model_dump_json())
        self.assertEqual(restored.failure.location, FailureLocation.get_status)
        self.assertEqual(restored.failure.probability, 0.25)
        self.assertEqual(restored.failure.exception.args, ('simulated',))

    async def test_invalid_location(self) -> None:
        with self.assertRaises(ValidationError):
            DummyConsumerFailure(location='unknown', exception=RuntimeError('simulated'))


if __name__ == '__main__':
    unittest.main()
