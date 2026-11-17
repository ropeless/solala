import unittest
from datetime import date
from unittest.mock import patch

from pydantic import ValidationError

from solala.settings import (
    DummySolarFailureDescription,
    DummySolarFailureLocation,
    DummySolarForecasterConnection,
)
from solala.delegates.solar_forecaster.dummy_solar_forecaster.dummy_solar_forecaster import DummySolarForecaster


class DummyFailureInjectorTestCase(unittest.IsolatedAsyncioTestCase):
    """
    Verify dummy solar fault injection and settings validation.
    """

    async def test_probability_zero_never_fails(self) -> None:
        forecaster = DummySolarForecaster(
            9000, 8000,
            inject_failure_probability=0.0,
            inject_failure_description=DummySolarFailureDescription(
                location=DummySolarFailureLocation.GET_FORECAST,
                exception=TimeoutError('simulated'),
            ),
        )
        await forecaster.get_forecast(date.today())

    async def test_probability_one_always_fails(self) -> None:
        forecaster = DummySolarForecaster(
            9000, 8000,
            inject_failure_probability=1.0,
            inject_failure_description=DummySolarFailureDescription(
                location=DummySolarFailureLocation.GET_FORECAST,
                exception=TimeoutError('simulated'),
            ),
        )
        with self.assertRaisesRegex(TimeoutError, 'simulated'):
            await forecaster.get_forecast(date.today())

    async def test_sleep_without_exception(self) -> None:
        forecaster = DummySolarForecaster(
            9000, 8000,
            inject_failure_probability=1.0,
            inject_failure_description=DummySolarFailureDescription(
                location=DummySolarFailureLocation.GET_FORECAST,
                sleep=2.0,
            ),
        )
        with patch('solala.utils.dummy_failure.asyncio.sleep', return_value=None) as sleep:
            await forecaster.get_forecast(date.today())
        sleep.assert_awaited_once_with(2.0)

    async def test_settings_json_round_trip(self) -> None:
        settings = DummySolarForecasterConnection(
            inject_failure_probability=0.5,
            inject_failure_description=DummySolarFailureDescription(
                location=DummySolarFailureLocation.GET_FORECAST,
                exception=ConnectionError('simulated'),
                sleep=1.0,
            ),
        )
        restored = DummySolarForecasterConnection.model_validate_json(settings.model_dump_json())
        self.assertEqual(restored.inject_failure_probability, 0.5)
        self.assertEqual(restored.inject_failure_description.location, DummySolarFailureLocation.GET_FORECAST)
        self.assertIs(type(restored.inject_failure_description.exception), ConnectionError)

    async def test_invalid_probability_and_location(self) -> None:
        with self.assertRaises(ValidationError):
            DummySolarForecasterConnection(inject_failure_probability=1.5)
        with self.assertRaises(ValidationError):
            DummySolarFailureDescription(location='UNKNOWN')


if __name__ == '__main__':
    unittest.main()
