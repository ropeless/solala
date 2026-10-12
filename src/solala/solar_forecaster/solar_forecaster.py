from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import List

from solala.utils.json import JSONDict


@dataclass
class SolarForecast:
    time: datetime  # local time
    irradiance: float  # W/m^2
    temperature: float  # Celsius
    power: float  # Wh

    def as_dict(self, datetime_format: str) -> JSONDict:
        result = {
            'time': self.time.strftime(datetime_format),
            'irradiance': self.irradiance,
            'temperature': self.temperature,
            'power': self.power,
        }
        return result


class SolarForecaster(ABC):
    @abstractmethod
    def get_forecast(self) -> List[SolarForecast]:
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
