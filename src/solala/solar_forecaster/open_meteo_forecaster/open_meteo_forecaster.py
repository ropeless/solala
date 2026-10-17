from datetime import datetime, timezone, date, timedelta
from typing import List

import httpx

from solala.settings import DEFAULT_INVERTER_LIMIT, DEFAULT_INVERTER_EFFICIENCY, DEFAULT_TEMPERATURE_COEFFICIENT
from solala.solar_forecaster.solar_forecaster import SolarForecaster, SolarForecast, DailySolarForecast, WeatherCode
from solala.utils.datetime_extras import ensure_date
from solala.utils.json import JSONDict

API_URL = "https://api.open-meteo.com/v1/forecast"


class OpenMeteoForecaster(SolarForecaster):
    """
    A basic solar forecaster that uses the Open-Meteo API and a simple
    model to forecast solar power output.
    """

    def __init__(
            self,
            *,
            latitude: float,
            longitude: float,
            panel_orientation: float,
            panel_tilt: float,
            panel_capacity: float,
            inverter_limit: float = DEFAULT_INVERTER_LIMIT,
            inverter_efficiency: float = DEFAULT_INVERTER_EFFICIENCY,
            temperature_coefficient: float = DEFAULT_TEMPERATURE_COEFFICIENT,
    ):
        """
        Args:
            latitude: Latitude of the location.
            longitude: Longitude of the location.
            panel_orientation: Orientation of the solar panel in degrees.
            panel_tilt: Tilt of the solar panel in degrees.
            panel_capacity: Capacity of the solar panel in W.
            inverter_limit: Power output limit of the inverter in W.
            inverter_efficiency: Efficiency of the inverter.
            temperature_coefficient: Temperature coefficient of the solar panel.
        """
        self._latitude = latitude
        self._longitude = longitude
        self._panel_orientation = panel_orientation
        self._panel_tilt = panel_tilt
        self._panel_capacity = panel_capacity
        self._inverter_limit = inverter_limit
        self._inverter_efficiency = inverter_efficiency
        self._temperature_coefficient = temperature_coefficient

    def get_forecast(self, day: date) -> DailySolarForecast:
        day: date = ensure_date(day)
        start_date = day - timedelta(days=1)
        end_date = day + timedelta(days=1)

        params = {
            'latitude': self._latitude,
            'longitude': self._longitude,
            'hourly': 'global_tilted_irradiance,'
                      'temperature_2m,'
                      'wind_speed_10m,'
                      'weather_code,'
                      'is_day',
            "tilt": self._panel_tilt,
            'azimuth': self._panel_orientation,
            'timezone': 'GMT',
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            'wind_speed_unit': 'ms',
        }

        response = httpx.get(API_URL, params=params)
        response.raise_for_status()
        data = response.json()

        hourly = data['hourly']
        now = datetime.now().astimezone()
        tz = now.tzinfo
        forecasts: List[SolarForecast] = []

        for timestamp, irradiance, temperature, wind_speed, weather_code, is_day in zip(
                hourly['time'],
                hourly['global_tilted_irradiance'],
                hourly['temperature_2m'],
                hourly['wind_speed_10m'],
                hourly['weather_code'],
                hourly['is_day'],
        ):
            # API timestamps are UTC; attach the UTC timezone.
            utc_time = datetime.fromisoformat(timestamp).replace(
                tzinfo=timezone.utc
            )
            local_time = utc_time.astimezone(tz)

            if local_time.date() != day:
                continue

            if irradiance is None:
                irradiance = 0

            forecasts.append(SolarForecast(
                time=local_time,
                irradiance=irradiance,
                temperature=temperature,
                power=self.power(irradiance, temperature, wind_speed),
                weather=_weather(weather_code, is_day)
            ))

        return DailySolarForecast(forecasts)

    def get_connection_status(self) -> JSONDict:
        return {
            'status': 'Open-Meteo connection',
            'latitude': self._latitude,
            'longitude': self._longitude,
            'panel_orientation': self._panel_orientation,
            'panel_tilt': self._panel_tilt,
        }

    def close(self) -> None:
        # nothing to do
        pass

    def power(
            self,
            irradiance: float,
            temperature: float,
            wind_speed: float,
    ) -> float:
        """
        Estimate PV output from forecast data.

        Args:
        Returns:
             estimated AC power in W.
        """

        irradiance = max(0.0, irradiance)
        wind = max(0.0, wind_speed)

        # Faiman-style module temperature estimate.
        cell_temp = temperature + irradiance / (
                25.0 + 6.84 * wind
        )

        # Temperature-corrected DC output.
        temp_factor = max(
            0.0,
            1.0 + self._temperature_coefficient * (cell_temp - 25.0),
        )

        dc_kw = self._panel_capacity * irradiance / 1000.0 * temp_factor

        # Simplified DC-to-AC conversion.
        ac_kw = max(0.0, min(dc_kw * self._inverter_efficiency, self._inverter_limit))

        return ac_kw


def _weather(code: int, is_day: bool) -> WeatherCode:
    if not is_day:
        return WeatherCode.NIGHT

    # Map an Open-Meteo WMO weather code to a Solala WeatherCode.
    if code == 0:
        return WeatherCode.CLEAR_DAY

    if code == 1:
        return WeatherCode.CLOUDY_1

    if code == 2:
        return WeatherCode.CLOUDY_2

    if code == 3:
        return WeatherCode.CLOUDY_4

    if code in (45, 48):
        return WeatherCode.FOG

    # Drizzle
    if code in (51, 53):
        return WeatherCode.RAINY_1
    if code == 55:
        return WeatherCode.RAINY_2

    # Freezing drizzle
    if code in (56, 57):
        return WeatherCode.RAIN_AND_SLEET_MIX

    # Rain
    if code == 61:
        return WeatherCode.RAINY_1
    if code == 63:
        return WeatherCode.RAINY_2
    if code == 65:
        return WeatherCode.RAINY_3

    # Freezing rain
    if code in (66, 67):
        return WeatherCode.RAIN_AND_SLEET_MIX

    # Snowfall
    if code in (71, 77):
        return WeatherCode.SNOWY_1
    if code == 73:
        return WeatherCode.SNOWY_2
    if code == 75:
        return WeatherCode.SNOWY_3

    # Rain showers
    if code == 80:
        return WeatherCode.RAINY_1
    if code == 81:
        return WeatherCode.RAINY_2
    if code == 82:
        return WeatherCode.RAINY_3

    # Snow showers
    if code == 85:
        return WeatherCode.SNOWY_1
    if code == 86:
        return WeatherCode.SNOWY_3

    # Thunderstorms
    if code == 95:
        return WeatherCode.THUNDERSTORMS
    if code == 96:
        return WeatherCode.THUNDERSTORM_SEVERE
    if code == 99:
        return WeatherCode.THUNDERSTORM_SEVERE

    return WeatherCode.UNKNOWN
