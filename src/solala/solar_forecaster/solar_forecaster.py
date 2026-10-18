from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, date
from enum import Enum, auto
from typing import Sequence, Iterator

from solala.utils.json import JSONDict, to_json


class WeatherCode(Enum):
    NIGHT = auto()

    CLEAR_DAY = auto()

    CLOUDY_1 = auto()
    CLOUDY_2 = auto()
    CLOUDY_3 = auto()
    CLOUDY_4 = auto()

    DUST = auto()
    FOG = auto()
    FROST = auto()
    HAIL = auto()
    HAZE = auto()

    RAINY_1 = auto()
    RAINY_2 = auto()
    RAINY_3 = auto()

    THUNDERSTORMS = auto()
    THUNDERSTORMS_ISOLATED = auto()
    THUNDERSTORMS_SCATTERED = auto()
    THUNDERSTORM_SEVERE = auto()
    HURRICANE = auto()
    TORNADO = auto()

    SNOWY_1 = auto()
    SNOWY_2 = auto()
    SNOWY_3 = auto()

    RAIN_AND_SLEET_MIX = auto()
    RAIN_AND_SNOW_MIX = auto()
    SNOW_AND_SLEET_MIX = auto()

    UNKNOWN = auto()


@dataclass(frozen=True)
class SolarForecast:
    time: datetime  # local time
    irradiance: float  # W/m^2
    temperature: float  # Celsius
    power: float  # Wh
    weather: WeatherCode

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
    def get_forecast(self, day: date) -> DailySolarForecast:
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
