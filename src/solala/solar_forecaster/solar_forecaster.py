from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, date
from typing import Sequence, Iterator

from solala.utils.json import JSONDict, to_json


@dataclass(frozen=True)
class SolarForecast:
    time: datetime  # local time
    irradiance: float  # W/m^2
    temperature: float  # Celsius
    power: float  # Wh

    def to_json(self, datetime_format: str) -> JSONDict:
        return to_json(self, datetime_format=datetime_format)


@dataclass(frozen=True)
class DailySolarForecast:
    """
    Hourly forecast of solar irradiance, temperature, and power for one day.
    """
    forecasts: Sequence[SolarForecast]

    def __iter__(self) -> Iterator[SolarForecast]:
        return iter(self.forecasts)

    def total_forecast_energy(self) -> float:
        """

        Returns:
            Forecast energy in Wh.
        """
        return sum(
            forecast.power
            for forecast in self.forecasts
        )

    def date(self) -> date:
        return self.forecasts[0].time.date()


class SolarForecaster(ABC):
    @abstractmethod
    def get_forecast(self, day_offset: int) -> DailySolarForecast:
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
