import asyncio
import importlib
import logging
import unittest
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from unittest.mock import AsyncMock, Mock, patch

from solala.logger import LOGGER
from solala.delegates.power_pricer.price import Price
from solala.delegates.solar_forecaster.solar_forecaster import DailySolarForecast

control_loop = importlib.import_module('solala.control_loop.control_loop')


class ConnectionCacheRaceTestCase(unittest.IsolatedAsyncioTestCase):
    """
    Verify that connection replacement cannot publish stale cached readings.
    """

    async def asyncSetUp(self) -> None:
        handlers = patch.object(LOGGER, 'handlers', [logging.NullHandler()])
        propagation = patch.object(LOGGER, 'propagate', False)
        handlers.start()
        propagation.start()
        self.addCleanup(propagation.stop)
        self.addCleanup(handlers.stop)

        self.state = control_loop._ControlState()
        self.state_patch = patch.object(control_loop, '_CONTROL_STATE', self.state)
        self.state_patch.start()
        self.addCleanup(self.state_patch.stop)

    @staticmethod
    def price(value: float) -> Price:
        start = datetime.now(UTC)
        return Price(
            start_time=start,
            end_time=start + timedelta(minutes=30),
            buy_price=value,
            feed_in_price=value,
            renewables=50,
            is_estimate=False,
        )

    async def test_pricer_replacement_during_refresh(self) -> None:
        started = asyncio.Event()
        release = asyncio.Event()
        old_price = self.price(10)
        new_price = self.price(20)

        async def old_get_price() -> Price:
            started.set()
            try:
                await release.wait()
            except asyncio.CancelledError:
                # Simulate a delegate that finishes despite cancellation.
                await release.wait()
            return old_price

        old_pricer = Mock(get_price=AsyncMock(side_effect=old_get_price))
        new_pricer = Mock(get_price=AsyncMock(return_value=new_price))
        self.state.connections.pricer = old_pricer

        old_call = asyncio.create_task(control_loop.get_price_now())
        await asyncio.wait_for(started.wait(), timeout=1)
        try:
            async def replace_pricer() -> None:
                async with control_loop._connections_state():
                    await self.state.reset_pricer(new_pricer, Mock())

            replacement = asyncio.create_task(replace_pricer())
            await asyncio.sleep(0)
        finally:
            release.set()

        await asyncio.wait_for(replacement, timeout=1)
        # The old waiter may be cancelled by invalidation; it must not publish old_price.
        await asyncio.gather(old_call, return_exceptions=True)
        self.assertEqual(await control_loop.get_price_now(), new_price)
        self.assertEqual(await control_loop.get_price_now(), new_price)
        new_pricer.get_price.assert_awaited_once()

    async def test_forecaster_replacement_during_refresh(self) -> None:
        day = date(2026, 11, 16)
        started = asyncio.Event()
        release = asyncio.Event()
        old_forecast = DailySolarForecast([])
        new_forecast = DailySolarForecast([])

        async def old_get_forecast(_day: date) -> DailySolarForecast:
            started.set()
            await release.wait()
            return old_forecast

        old_forecaster = Mock(get_forecast=AsyncMock(side_effect=old_get_forecast))
        new_forecaster = Mock(get_forecast=AsyncMock(return_value=new_forecast))
        self.state.connections.forecaster = old_forecaster

        old_call = asyncio.create_task(control_loop.get_solar_forecast(day))
        await asyncio.wait_for(started.wait(), timeout=1)
        try:
            async with control_loop._connections_state():
                await self.state.reset_forecaster(new_forecaster, Mock())
            result = await control_loop.get_solar_forecast(day)
            self.assertIs(result, new_forecast)
            self.assertIs(await control_loop.get_solar_forecast(day), new_forecast)
            new_forecaster.get_forecast.assert_awaited_once_with(day)
        finally:
            release.set()

        # An obsolete caller can complete, but cannot replace the current cache.
        await asyncio.wait_for(old_call, timeout=1)
        self.assertIs(await control_loop.get_solar_forecast(day), new_forecast)

    async def test_controller_replacement_waits_for_status_read(self) -> None:
        started = asyncio.Event()
        release = asyncio.Event()
        old_status = replace(control_loop._NO_POWER, solar_power=100)
        new_status = replace(control_loop._NO_POWER, solar_power=200)

        async def old_get_status():
            started.set()
            await release.wait()
            return old_status

        old_controller = Mock(get_status=AsyncMock(side_effect=old_get_status))
        new_controller = Mock(get_status=AsyncMock(return_value=new_status))
        self.state.connections.controller = old_controller

        old_call = asyncio.create_task(control_loop.get_power_status())
        await asyncio.wait_for(started.wait(), timeout=1)

        async def replace_controller() -> None:
            async with control_loop._connections_state():
                await self.state.reset_controller(new_controller, Mock())

        replacement = asyncio.create_task(replace_controller())
        try:
            await asyncio.sleep(0)
            self.assertFalse(replacement.done(), 'replacement must wait for the active status read')
        finally:
            release.set()

        self.assertEqual(await asyncio.wait_for(old_call, timeout=1), old_status)
        await asyncio.wait_for(replacement, timeout=1)
        self.assertEqual(await control_loop.get_power_status(), new_status)
        self.assertEqual(await control_loop.get_power_status(), new_status)
        new_controller.get_status.assert_awaited_once()


if __name__ == '__main__':
    unittest.main()
