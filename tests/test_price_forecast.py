import importlib
import logging
import unittest
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

from solala.logger import LOGGER
from solala.delegates.power_pricer.price import Price
from solala.utils.lifecycle_cache import ErrorReturn, ObjectReturn

control_loop = importlib.import_module('solala.control_loop.control_loop')


class PriceForecastTestCase(unittest.IsolatedAsyncioTestCase):
    """
    Verify price forecast handling when a pricer returns no intervals.
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
        self.pricer = AsyncMock()
        self.state.connections.pricer = self.pricer

    async def test_empty_forecast_returns_error(self) -> None:
        self.pricer.get_price_forecast.return_value = []

        result = await control_loop._get_price_forecast()

        self.assertIsInstance(result, ErrorReturn)
        self.assertIn('no prices', result.message)

    async def test_empty_forecast_uses_cached_fallback(self) -> None:
        self.pricer.get_price_forecast.return_value = []

        self.assertEqual(await control_loop.get_price_forecast(), ())
        self.pricer.get_price_forecast.assert_awaited_once()

    async def test_nonempty_forecast_preserves_refresh_deadline(self) -> None:
        start = datetime.now(UTC)
        price = Price(
            start_time=start,
            end_time=start + timedelta(minutes=30),
            buy_price=10,
            feed_in_price=5,
            renewables=50,
            is_estimate=False,
        )
        self.pricer.get_price_forecast.return_value = [price]

        result = await control_loop._get_price_forecast()

        self.assertIsInstance(result, ObjectReturn)
        self.assertEqual(result.value, [price])
        self.assertEqual(result.refresh_at, price.end_time)


if __name__ == '__main__':
    unittest.main()
