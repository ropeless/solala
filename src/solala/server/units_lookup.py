# Units for pretty printing status
from collections.abc import Mapping

from solala.constants import Units
from solala.utils.dict_extras import dict_merge

PARAMETERS_UNITS: Mapping[str, str] = {
    'start_charge_price_threshold': Units.PRICE_CENTS,
    'stop_charge_price_threshold': Units.PRICE_CENTS,
    'disable_export_price_threshold': Units.PRICE_CENTS,
    'enable_export_price_threshold': Units.PRICE_CENTS,
}
STATUS_UNITS: Mapping[str, str] = dict_merge(
    {
        'buy_price': Units.PRICE_CENTS,
        'feed_in_price': Units.PRICE_CENTS,
        'renewables': Units.PERCENT,
        'state_of_charge': Units.PERCENT,
        'power_limit': Units.PERCENT,
        'grid_power': Units.WATTS,
        'solar_power': Units.WATTS,
        'battery_power': Units.WATTS,
        'house_power': Units.WATTS,
        'consumers_total': Units.WATTS,
        'consumers_remaining': Units.WATTS,
        'power': Units.WATTS,
        'voltage': Units.VOLTS,
        'current': Units.AMPS,
        'capacity': Units.WATTS,
        'forecast_generation': Units.KILOWATT_HOURS,
    },
    PARAMETERS_UNITS,
)
CONSTANTS_UNITS: Mapping[str, str] = {
    'LOOP_TIME': Units.SECONDS,
    'LOOP_MIN_SLEEP_TIME': Units.SECONDS,
    'CONTROL_DURATION': Units.SECONDS,
    'PRICE_LOOK_AHEAD': Units.MINUTES,
    'PRICE_SETTLE_CHECK': Units.SECONDS,
    'PRICE_FORECAST_DURATION': Units.HOURS,
    'PRICE_FORECAST_AGE': Units.MINUTES,
    'SOLAR_FORECAST_AGE': Units.MINUTES,
}
CONNECTION_UNITS: Mapping[str, str] = {
    'latitude': Units.DEGREES,
    'longitude': Units.DEGREES,
    'panel_orientation': Units.DEGREES,
    'panel_tilt': Units.DEGREES,
    'panel_capacity': Units.WATTS,
    'panel_temperature_coefficient': Units.CELSIUS,
    'inverter_limit': Units.WATTS,
}


