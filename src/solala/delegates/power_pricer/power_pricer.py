from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import List

from solala.utils.json import JSONDict, to_json


@dataclass(frozen=True)
class Price:
    buy_price: float  # c per kWh
    feed_in_price: float  # c per kWh
    renewables: float  # percentage
    start_time: datetime  # date + time + timezone
    end_time: datetime  # date + time + timezone
    estimate: bool  # whether the price is an estimate or not

    # Optional tariff information.
    tariff_period: str = ''
    tariff_season: str = ''
    tariff_demand_window: bool = False

    def to_json(self, datetime_format: str, include_time: bool) -> JSONDict:
        exclude_names = set() if include_time else {'start_time', 'end_time'}
        exclude_values = ('',)
        return to_json(
            self,
            datetime_format=datetime_format,
            exclude_names=exclude_names,
            exclude_values=exclude_values,
        )


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
    def get_connection_status(self) -> JSONDict:
        """
        Get the status of the connection.
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
        return exc_type is None
