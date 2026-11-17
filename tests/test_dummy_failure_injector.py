import unittest
from datetime import date
from unittest.mock import AsyncMock, patch

from pydantic import ValidationError

from solala.delegates.solar_forecaster.dummy_solar_forecaster.dummy_solar_forecaster import (
    DummySolarForecaster, FailureLocation,
)
from solala.settings import DummySolarFailure, DummySolarForecasterConnection


class DummyFailureInjectorTestCase(unittest.IsolatedAsyncioTestCase):
    """
    Verify dummy solar fault injection and settings validation.
    """

    async def test_no_configured_failure(self) -> None:
        await DummySolarForecaster(9000, 8000).get_forecast(date.today())

    async def test_probability_one_always_fails(self) -> None:
        forecaster = DummySolarForecaster(
            9000, 8000,
            failure=DummySolarFailure(
                location=FailureLocation.get_forecast,
                exception=TimeoutError('simulated'),
            ),
        )
        with self.assertRaisesRegex(TimeoutError, 'simulated'):
            await forecaster.get_forecast(date.today())

    async def test_probability_half_respects_random_draw(self) -> None:
        forecaster = DummySolarForecaster(
            9000, 8000,
            failure=DummySolarFailure(
                location=FailureLocation.get_forecast,
                probability=0.5,
                exception=TimeoutError('simulated'),
            ),
        )
        with patch('solala.utils.dummy_failure.random.random', return_value=0.8):
            await forecaster.get_forecast(date.today())
        with patch('solala.utils.dummy_failure.random.random', return_value=0.2):
            with self.assertRaises(TimeoutError):
                await forecaster.get_forecast(date.today())

    async def test_sleep_without_exception(self) -> None:
        forecaster = DummySolarForecaster(
            9000, 8000,
            failure=DummySolarFailure(
                location=FailureLocation.get_forecast,
                sleep=2.0,
            ),
        )
        with patch('solala.utils.dummy_failure.asyncio.sleep', new_callable=AsyncMock) as sleep:
            await forecaster.get_forecast(date.today())
        sleep.assert_awaited_once_with(2.0)

    async def test_sync_failure_location(self) -> None:
        forecaster = DummySolarForecaster(
            9000, 8000,
            failure=DummySolarFailure(
                location=FailureLocation.get_connection_info,
                exception=RuntimeError('simulated'),
            ),
        )
        with self.assertRaisesRegex(RuntimeError, 'simulated'):
            forecaster.get_connection_info()

    async def test_sync_delay_is_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            DummySolarFailure(
                location=FailureLocation.get_connection_info,
                sleep=1.0,
            )

    async def test_settings_json_round_trip(self) -> None:
        settings = DummySolarForecasterConnection(
            failure=DummySolarFailure(
                location=FailureLocation.get_forecast,
                probability=0.5,
                exception=ConnectionError('simulated'),
                sleep=1.0,
            ),
        )
        restored = DummySolarForecasterConnection.model_validate_json(settings.model_dump_json())
        self.assertEqual(restored.failure.probability, 0.5)
        self.assertEqual(restored.failure.location, FailureLocation.get_forecast)
        self.assertIs(type(restored.failure.exception), ConnectionError)

    async def test_invalid_configuration(self) -> None:
        for probability in (0.0, 1.5):
            with self.subTest(probability=probability):
                with self.assertRaises(ValidationError):
                    DummySolarFailure(
                        location=FailureLocation.get_forecast,
                        probability=probability,
                        exception=RuntimeError('simulated'),
                    )
        with self.assertRaises(ValidationError):
            DummySolarFailure(location='UNKNOWN', exception=RuntimeError('simulated'))
        with self.assertRaises(ValidationError):
            DummySolarFailure(location=FailureLocation.get_forecast)


if __name__ == '__main__':
    unittest.main()
