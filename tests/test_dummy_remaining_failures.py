import unittest
from datetime import date
from unittest.mock import AsyncMock, patch

from pydantic import ValidationError

from solala.delegates.power_pricer.dummy_power_pricer.dummy_power_pricer import (
    DummyPowerPricer, FailureLocation as PricerLocation,
)
from solala.delegates.power_controller.dummy_power_controller.dummy_power_controller import (
    DummyPowerController, FailureLocation as ControllerLocation,
)
from solala.settings import (
    DummyControllerConnection, DummyControllerFailure,
    DummyPricerConnection, DummyPricerFailure,
)


def make_controller(failure: DummyControllerFailure | None = None) -> DummyPowerController:
    return DummyPowerController(
        inverter_limit=8000,
        house_power=3000,
        max_charge_param=3000,
        max_discharge_param=3000,
        failure=failure,
    )


class DummyPricerFailureTestCase(unittest.IsolatedAsyncioTestCase):
    """
    Verify simulated price failures and configuration persistence.
    """

    async def test_no_failure(self) -> None:
        pricer = DummyPowerPricer()
        await pricer.get_price()
        await pricer.get_price_forecast(1)
        await pricer.get_demand_window(date.today())
        pricer.get_connection_info()

    async def test_get_price_exception(self) -> None:
        pricer = DummyPowerPricer(failure=DummyPricerFailure(
            location=PricerLocation.get_price, exception=TimeoutError('simulated'),
        ))
        with self.assertRaisesRegex(TimeoutError, 'simulated'):
            await pricer.get_price()

    async def test_forecast_exception(self) -> None:
        pricer = DummyPowerPricer(failure=DummyPricerFailure(
            location=PricerLocation.get_price_forecast, exception=RuntimeError('simulated'),
        ))
        with self.assertRaises(RuntimeError):
            await pricer.get_price_forecast(1)
        await pricer.get_price()

    async def test_demand_window_delay(self) -> None:
        pricer = DummyPowerPricer(failure=DummyPricerFailure(
            location=PricerLocation.get_demand_window, sleep=1.0,
        ))
        with patch('solala.utils.dummy_failure.asyncio.sleep', new_callable=AsyncMock) as sleep:
            await pricer.get_demand_window(date.today())
        sleep.assert_awaited_once_with(1.0)

    async def test_connection_info_exception(self) -> None:
        pricer = DummyPowerPricer(failure=DummyPricerFailure(
            location=PricerLocation.get_connection_info, exception=ConnectionError('simulated'),
        ))
        with self.assertRaises(ConnectionError):
            pricer.get_connection_info()

    async def test_settings_round_trip(self) -> None:
        settings = DummyPricerConnection(failure=DummyPricerFailure(
            location=PricerLocation.get_price, probability=0.25,
            exception=TimeoutError('simulated'),
        ))
        restored = DummyPricerConnection.model_validate_json(settings.model_dump_json())
        self.assertEqual(restored.failure.location, PricerLocation.get_price)
        self.assertEqual(restored.failure.probability, 0.25)
        self.assertEqual(restored.failure.exception.args, ('simulated',))


class DummyControllerFailureTestCase(unittest.IsolatedAsyncioTestCase):
    """
    Verify simulated controller failures and configuration persistence.
    """

    async def test_no_failure(self) -> None:
        controller = make_controller()
        await controller.get_status()
        await controller.get_registers()
        await controller.get_inverter_limit()
        await controller.enable_battery()

    async def test_get_status_exception(self) -> None:
        controller = make_controller(DummyControllerFailure(
            location=ControllerLocation.get_status, exception=TimeoutError('simulated'),
        ))
        with self.assertRaises(TimeoutError):
            await controller.get_status()

    async def test_control_command_failure_does_not_change_mode(self) -> None:
        controller = make_controller(DummyControllerFailure(
            location=ControllerLocation.force_charge, exception=RuntimeError('simulated'),
        ))
        initial_mode = controller.battery_mode
        with self.assertRaises(RuntimeError):
            await controller.force_charge()
        self.assertEqual(controller.battery_mode, initial_mode)

    async def test_get_registers_delay(self) -> None:
        controller = make_controller(DummyControllerFailure(
            location=ControllerLocation.get_registers, sleep=1.0,
        ))
        with patch('solala.utils.dummy_failure.asyncio.sleep', new_callable=AsyncMock) as sleep:
            await controller.get_registers()
        sleep.assert_awaited_once_with(1.0)

    async def test_connection_info_exception(self) -> None:
        # The constructor calls get_connection_info() to build registers.
        with self.assertRaises(ConnectionError):
            make_controller(DummyControllerFailure(
                location=ControllerLocation.get_connection_info,
                exception=ConnectionError('simulated'),
            ))

    async def test_settings_round_trip(self) -> None:
        settings = DummyControllerConnection(failure=DummyControllerFailure(
            location=ControllerLocation.zero_export, probability=0.5,
            exception=RuntimeError('simulated'),
        ))
        restored = DummyControllerConnection.model_validate_json(settings.model_dump_json())
        self.assertEqual(restored.failure.location, ControllerLocation.zero_export)
        self.assertEqual(restored.failure.probability, 0.5)
        self.assertIs(type(restored.failure.exception), RuntimeError)

    async def test_invalid_location(self) -> None:
        with self.assertRaises(ValidationError):
            DummyControllerFailure(location='unknown', exception=RuntimeError('simulated'))


if __name__ == '__main__':
    unittest.main()
