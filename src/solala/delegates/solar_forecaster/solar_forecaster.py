from abc import ABC, abstractmethod
from datetime import date

from solala.delegates.solar_forecaster.solar_forecast import DailySolarForecast
from solala.utils.json import JSONDict


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
