from datetime import datetime

from pydantic import BaseModel

from solala.control_loop.modes_and_policies import BatteryMode, BatteryPolicy, InverterMode, InverterPolicy
from solala.delegates.solar_forecaster.weather_code import WeatherCode


class Measurement(BaseModel):
    """
    Snapshot of power-system readings, operating modes, and solar forecast data.

    Power measurements are in watts, accumulated energy measurements in
    watt-hours, and forecast irradiance in watts per square metre. The
    timestamp identifies when the snapshot was collected.

    Attributes:
        timestamp: Time at which the measurement was taken, with timezone.
        solar_power: Solar generation power.
        grid_power: Power exchanged with the grid.
        house_power: Household consumption power.
        battery_power: Battery power.
        battery_charge: Battery state of charge.
        buy_price: Electricity import price.
        feed_in_price: Electricity export price.
        renewables: Renewable energy proportion.
        accumulated_solar_energy: Cumulative solar generation.
        accumulated_grid_energy_import: Cumulative energy imported from the grid.
        accumulated_grid_energy_export: Cumulative energy exported to the grid.
        accumulated_battery_energy_charge: Cumulative battery charging energy.
        accumulated_battery_energy_discharge: Cumulative battery discharging energy.
        battery_mode: Current battery operating mode.
        battery_policy: Current battery control policy.
        inverter_mode: Current inverter operating mode.
        inverter_policy: Current inverter control policy.
        forecast_irradiance: Forecast irradiance in W/m².
        forecast_temperature: Forecast ambient temperature in degrees Celsius.
        forecast_power: Forecast solar power in watts.
        forecast_weather: Forecast weather condition.
    """
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
