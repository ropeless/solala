from datetime import datetime

from pydantic import BaseModel

from solala.control_loop.modes_and_policies import BatteryMode, BatteryPolicy, InverterMode, InverterPolicy
from solala.delegates.solar_forecaster.weather_code import WeatherCode


class Measurement(BaseModel):
    timestamp: datetime

    solar_power: float
    grid_power: float
    house_power: float
    battery_power: float
    battery_charge: float

    buy_price: float
    feed_in_price: float
    renewables: float

    accumulated_solar_energy: float
    accumulated_grid_energy_import: float
    accumulated_grid_energy_export: float
    accumulated_battery_energy_charge: float
    accumulated_battery_energy_discharge: float

    battery_mode: BatteryMode
    battery_policy: BatteryPolicy
    inverter_mode: InverterMode
    inverter_policy: InverterPolicy

    forecast_irradiance: float  # W/m^2
    forecast_temperature: float  # Celsius
    forecast_power: float  # W
    forecast_weather: WeatherCode
