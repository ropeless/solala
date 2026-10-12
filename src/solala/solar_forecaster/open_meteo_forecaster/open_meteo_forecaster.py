from datetime import datetime, timezone
from typing import List

import httpx

from solala.settings import DEFAULT_INVERTER_LIMIT, DEFAULT_INVERTER_EFFICIENCY, DEFAULT_TEMPERATURE_COEFFICIENT
from solala.solar_forecaster.solar_forecaster import SolarForecaster, SolarForecast
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

    def get_forecast(self) -> List[SolarForecast]:
        params = {
            'latitude': self._latitude,
            'longitude': self._longitude,
            'hourly': 'global_tilted_irradiance,temperature_2m,wind_speed_10m',
            "tilt": self._panel_tilt,
            'azimuth': self._panel_orientation,
            'timezone': 'GMT',
            'past_days': 1,
            'forecast_days': 2,
            'wind_speed_unit': 'ms',
        }

        response = httpx.get(API_URL, params=params)
        response.raise_for_status()
        data = response.json()

        hourly = data['hourly']
        now = datetime.now().astimezone()
        today = now.date()
        tz = now.tzinfo
        result: List[SolarForecast] = []

        for timestamp, irradiance, temperature, wind_speed in zip(
                hourly['time'],
                hourly['global_tilted_irradiance'],
                hourly['temperature_2m'],
                hourly['wind_speed_10m'],
        ):
            # API timestamps are UTC; attach the UTC timezone.
            utc_time = datetime.fromisoformat(timestamp).replace(
                tzinfo=timezone.utc
            )
            local_time = utc_time.astimezone(tz)

            if local_time.date() != today:
                continue

            if irradiance is None:
                irradiance = 0

            result.append(SolarForecast(
                time=local_time,
                irradiance=irradiance,
                temperature=temperature,
                power=self.power(irradiance, temperature, wind_speed)
            ))

        return result

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
