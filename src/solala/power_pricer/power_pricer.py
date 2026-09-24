from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import List

from solala.utils.json import JSONDict


@dataclass(frozen=True)
class Price:
    start_time: datetime  # date + time + timezone
    end_time: datetime  # date + time + timezone
    renewables: float  # percentage
    buy_price: float  # c per kWh
    feed_in_price: float  # c per kWh

    # Optional tariff information.
    tariff_period: str = ''
    tariff_season: str = ''
    tariff_demand_window: bool = False

    def as_dict(self, datetime_format: str) -> JSONDict:
        return {
            'start_time': self.start_time.strftime(datetime_format),
            'end_time': self.end_time.strftime(datetime_format),
            'renewables': self.renewables,
            'buy_price': self.buy_price,
            'feed_in_price': self.feed_in_price,
            'tariff_period': self.tariff_period,
            'tariff_season': self.tariff_season,
            'tariff_demand_window': self.tariff_demand_window,
        }


class PowerPricer(ABC):

    @abstractmethod
    def get_price(self, forecasts: int) -> List[Price]:
        """
        Get the current price and any requested price forecasts,
        in ascending order of time from now.

        The pricing interval is 5 minutes, so `forecasts = 12` covers
        1 hour and will return 13 prices.

        Args:
            forecasts: number of forecasts to return, >= 0.

        Returns:
            one or more prices, in ascending order.
        """
        ...

    @abstractmethod
    def close(self) -> None:
        """
        Close any connections to the pricing system.
        """
        ...

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return exc_type is None
