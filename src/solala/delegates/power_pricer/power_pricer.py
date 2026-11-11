from abc import ABC, abstractmethod
from datetime import date, datetime
from typing import List, Optional, Tuple

from solala.delegates.power_pricer.price import Price
from solala.utils.json_extras import JSONDict


class PowerPricer(ABC):

    @abstractmethod
    async def get_price(self) -> Price:
        """
        Get the current price.
        """
        ...

    @abstractmethod
    async def get_price_forecast(self, count: int) -> List[Price]:
        """
        Get the 30-minute price forecasts, in ascending order of time from now.

        The pricing interval is 30 minutes, so `count = 12` covers
        6 hours and will return 12 prices.

        Args:
            count: number of prices, >= 1.

        Returns:
            `count` prices, in ascending time order.
        """
        ...

    @abstractmethod
    async def get_demand_window(self, day: date) -> Optional[Tuple[datetime, datetime]]:
        """
        Get the demand window for the given day, if active.
        """
        ...

    @abstractmethod
    def get_connection_info(self) -> JSONDict:
        """
        Get information about the connection.
        """
        ...

    @abstractmethod
    async def close(self) -> None:
        """
        Close any connections to the pricing system.
        """
        ...

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        await self.close()
