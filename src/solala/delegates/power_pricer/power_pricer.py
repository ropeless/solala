from abc import ABC, abstractmethod
from datetime import date, datetime
from types import TracebackType
from typing import Self

from solala.delegates.power_pricer.price import Price
from solala.utils.json_extras import JSONDict


class PowerPricer(ABC):
    """
    Defines the interface for retrieving electricity prices and tariff information.
    """

    @abstractmethod
    async def get_price(self) -> Price:
        """
        Get the current five-minute pricing interval.

        Returns:
            The current price.
        """
        ...

    @abstractmethod
    async def get_price_forecast(self, count: int) -> list[Price]:
        """
        Get the 30-minute price forecasts, in ascending order of time from now.

        The pricing interval is 30 minutes, so `count = 12` covers
        6 hours and will return 12 prices.

        Args:
            count: Number of 30-minute forecast intervals, >= 1.

        Returns:
            `count` prices, in chronological order.
        """
        ...

    @abstractmethod
    async def get_demand_window(self, day: date) -> tuple[datetime, datetime] | None:
        """
        Get the demand window for the given day, if active.

        The returned datetimes represent the local start and end of the demand
        window. Returns `None` if no demand window applies.

        Args:
            day: The date for which to retrieve the demand window.
        """
        ...

    @abstractmethod
    def get_connection_info(self) -> JSONDict:
        """
        Get information about the pricing connection.

        Returns:
            A JSON-compatible dictionary describing the connection.
        """
        ...

    @abstractmethod
    async def close(self) -> None:
        """
        Close any connections to the pricing system.
        """
        ...

    async def __aenter__(self) -> Self:
        """
        Enter the asynchronous context manager.

        Returns:
            This power pricer.
        """
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """
        Exit the asynchronous context manager and close the power pricer.
        """
        await self.close()
