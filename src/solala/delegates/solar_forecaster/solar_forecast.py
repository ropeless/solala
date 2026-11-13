from dataclasses import dataclass
from datetime import datetime
from collections.abc import Iterator, Sequence

from solala.delegates.solar_forecaster.weather_code import WeatherCode
from solala.utils.json_extras import to_json, JSONDict


@dataclass(frozen=True)
class SolarForecast:
    start_time: datetime  # date + time + timezone (local time)
    end_time: datetime  # date + time + timezone (local time)
    weather: WeatherCode
    irradiance: float  # W/m^2
    temperature: float  # Celsius
    power: float  # W

    @property
    def energy(self) -> float:
        """
        Returns:
            Forecast energy in Wh.
        """
        return self.power * (self.end_time - self.start_time).total_seconds() / 3600

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
            forecast.energy
            for forecast in self.forecasts
        )

    def find_contemporary(self, dt: datetime) -> SolarForecast | None:
        """
        Returns:
            The forecast covering the given datetime.
        """
        forecasts = self.forecasts
        if len(forecasts) == 0:
            return None
        tz = forecasts[0].start_time.tzinfo
        dt_local = dt.astimezone(tz)

        for forecast in self.forecasts:
            if forecast.start_time <= dt_local < forecast.end_time:
                return forecast
        return None
