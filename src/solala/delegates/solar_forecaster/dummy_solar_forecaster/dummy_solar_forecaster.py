import random
from datetime import datetime, timedelta, date

from solala.delegates.solar_forecaster.solar_forecast import DailySolarForecast, SolarForecast
from solala.delegates.solar_forecaster.solar_forecaster import SolarForecaster
from solala.delegates.solar_forecaster.weather_code import WeatherCode
from solala.utils.datetime_extras import ensure_date, date_to_datetime
from solala.utils.json_extras import JSONDict


class DummySolarForecaster(SolarForecaster):
    """
    Dummy solar forecaster that generates synthetic hourly forecasts for
    testing and development.

    Its public attributes can be updated after construction to adjust the
    generated forecasts.
    """

    def __init__(self, panel_capacity: float, inverter_limit: float):
        """
        Initialise the dummy solar forecaster.

        Args:
            panel_capacity: Installed solar panel capacity in W.
            inverter_limit: Maximum inverter output power in W.
        """
        self.panel_capacity: float = panel_capacity
        self.inverter_limit: float = inverter_limit
        self._tz = datetime.now().astimezone().tzinfo

        # Create dummy forecasts, for today, assuming power limit is 1.
        self.irradiance = {
            7: 5,
            8: 26,
            9: 164,
            10: 279,
            11: 365,
            12: 231,
            13: 310,
            14: 396,
            15: 114,
            16: 124,
            17: 138,
            18: 148,
            19: 48,
        }
        self.temperature: list[float] = [
            21, 20, 19, 18, 18, 17, 17, 17, 17, 18, 20, 19,
            19, 19, 20, 17, 17, 17, 17, 16, 15, 15, 15,
        ]

    async def get_forecast(self, day: date) -> DailySolarForecast:
        """
        Generate a synthetic daily forecast using predefined hourly irradiance
        and temperature values, with randomly selected daytime weather
        conditions.
        """
        day_of_interest: datetime = date_to_datetime(ensure_date(day)).replace(tzinfo=self._tz)
        limit = max(self.panel_capacity, self.inverter_limit)

        night = WeatherCode.NIGHT
        day = list(WeatherCode)
        day.remove(night)

        forecasts: list[SolarForecast] = [
            SolarForecast(
                start_time=day_of_interest + timedelta(hours=hour),
                end_time=day_of_interest + timedelta(hours=hour + 1),
                irradiance=self.irradiance.get(hour, 0),
                temperature=self.temperature[hour],
                power=min(self.irradiance.get(hour, 0) / 1000 * self.panel_capacity, limit),
                weather=night if hour not in self.irradiance else random.choice(day),
            )
            for hour in range(24)
        ]
        return DailySolarForecast(forecasts)

    def get_connection_info(self) -> JSONDict:
        """
        Return the configuration used by this dummy forecaster.

        Returns:
            A dictionary containing the forecaster class name, panel capacity,
            inverter limit, and timezone.
        """
        return {
            'connection': self.__class__.__name__,
            'panel_capacity': self.panel_capacity,
            'inverter_limit': self.inverter_limit,
            'timezone': str(self._tz),
        }

    async def close(self) -> None:
        # nothing to do
        pass
