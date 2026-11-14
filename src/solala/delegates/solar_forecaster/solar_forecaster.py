from abc import ABC, abstractmethod
from datetime import date
from types import TracebackType
from typing import Self

from solala.delegates.solar_forecaster.solar_forecast import DailySolarForecast
from solala.utils.json_extras import JSONDict


class SolarForecaster(ABC):
    """
    Defines the interface for obtaining daily solar irradiance and temperature
    forecasts.
    """

    @abstractmethod
    async def get_forecast(self, day: date) -> DailySolarForecast:
        """
        Get an hourly forecast of solar irradiance and temperature for a day.

        Implementations should account for local conditions and daily weather,
        including cloud cover.

        Args:
            day: Date for which to obtain the forecast.

        Returns:
            The hourly solar irradiance and temperature forecast for the day.
        """
        ...

    @abstractmethod
    def get_connection_info(self) -> JSONDict:
        """
        Get information about the connection.

        Returns:
            A JSON-compatible dictionary describing the connection.
        """
        ...

    @abstractmethod
    async def close(self) -> None:
        """
        Close any connections used by the solar forecaster.
        """
        ...

    async def __aenter__(self) -> Self:
        """
        Enter the asynchronous context manager.

        Returns:
            This solar forecaster.
        """
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """
        Exit the asynchronous context manager and close the solar forecaster.
        """
        await self.close()
