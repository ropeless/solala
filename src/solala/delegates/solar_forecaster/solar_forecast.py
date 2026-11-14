from dataclasses import dataclass
from datetime import datetime
from collections.abc import Iterator, Sequence

from solala.delegates.solar_forecaster.weather_code import WeatherCode
from solala.utils.json_extras import to_json, JSONDict


@dataclass(frozen=True)
class SolarForecast:
    """
    Forecast of solar conditions and power for a single time interval (should be 1 hour).

    Attributes:
        start_time: Start of the forecast interval, as a datetime with timezone, in local time.
        end_time: End of the forecast interval, as a datetime with timezone, in local time.
        weather: Forecast weather conditions.
        irradiance: Solar irradiance in W/m².
        temperature: Forecast temperature in °C.
        power: Forecast solar power in W.
    """

    start_time: datetime  # date + time + timezone (local time)
    end_time: datetime  # date + time + timezone (local time)
    weather: WeatherCode
    irradiance: float
    temperature: float
    power: float

    @property
    def energy(self) -> float:
        """
        Get the forecast energy generated over this interval.

        Returns:
            Forecast energy in Wh.
        """
        return self.power * (self.end_time - self.start_time).total_seconds() / 3600

    def to_json(self, datetime_format: str) -> JSONDict:
        """
        Convert the forecast to a JSON-compatible dictionary.

        Args:
            datetime_format: Format string used to serialize datetime values.

        Returns:
            The forecast represented as a JSON-compatible dictionary.
        """
        return to_json(self, datetime_format=datetime_format)


@dataclass(frozen=True)
class DailySolarForecast:
    """
    Collection of hourly solar forecasts for one day.

    Attributes:
        forecasts: Solar forecasts making up the daily forecast.
    """

    forecasts: Sequence[SolarForecast]

    def __iter__(self) -> Iterator[SolarForecast]:
        """
        Iterate over the individual solar forecasts.

        Returns:
            An iterator over the daily solar forecasts.
        """
        return iter(self.forecasts)

    def total_forecast_energy(self) -> float:
        """
        Calculate the total forecast energy for the day.

        Returns:
            Total forecast energy in Wh.
        """
        return sum(
            forecast.energy
            for forecast in self.forecasts
        )

    def find_contemporary(self, when: datetime) -> SolarForecast | None:
        """
        Find the forecast interval containing a given datetime.

        The datetime is converted to the forecast timezone before comparison.

        Args:
            when: Datetime to find within the daily forecast.

        Returns:
            The forecast interval containing the datetime, or None if no interval
            matches.
        """
        forecasts = self.forecasts
        if len(forecasts) == 0:
            return None
        tz = forecasts[0].start_time.tzinfo
        when_local = when.astimezone(tz)

        for forecast in self.forecasts:
            if forecast.start_time <= when_local < forecast.end_time:
                return forecast
        return None
