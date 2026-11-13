from abc import ABC, abstractmethod
from datetime import date
from types import TracebackType
from typing import Self

from solala.delegates.solar_forecaster.solar_forecast import DailySolarForecast
from solala.utils.json_extras import JSONDict


class SolarForecaster(ABC):
    @abstractmethod
    async def get_forecast(self, day: date) -> DailySolarForecast:
        """
        Provide an hourly forecast of solar irradiance and temperature for today.
        The implementer should account for the local conditions and daily weather
        (such as cloud cover).
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

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.close()
