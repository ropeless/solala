"""
Default configuration values, display units, and application constants.

Price thresholds use cents per kilowatt-hour unless otherwise specified.
"""
from datetime import timedelta

from solala.utils.json_extras import JSONDict, to_json

DEFAULT_DISABLE_FEED_IN_PRICE_THRESHOLD: float = -0.1  # disable export below this price
DEFAULT_ENABLE_FEED_IN_PRICE_THRESHOLD: float = 0.1  # re-enable export above this price
DEFAULT_START_CHARGE_PRICE_THRESHOLD: float = 10  # start force charging below this price
DEFAULT_STOP_CHARGE_PRICE_THRESHOLD: float = 11  # stop force charging above this price

DEFAULT_INVERTER_EFFICIENCY: float = 0.96  # as a fraction (0 to 1)
DEFAULT_INVERTER_LIMIT: float = float('inf')  # in Watts
DEFAULT_PANEL_TEMPERATURE_COEFFICIENT: float = -0.004  # in Celsius

DEFAULT_DB_HOST: str = 'localhost'
DEFAULT_DB_PORT: int = 5432
DEFAULT_DB_NAME: str = 'solala'

GUI_TIMESTAMP_FORMAT = '%Y-%m-%d %H:%M:%S (%Z)'  # format for human-readable timestamps
GUI_DATE_FORMAT = '%a, %d %b %Y'
GUI_TIME_FORMAT = '%H:%M'
GUI_LOG_FORMAT: str = '%(asctime)s %(levelname)s: %(name)s %(message)s'


class Units:
    """
    Unit suffixes used when formatting quantities for display.

    Most suffixes include a leading space to separate them from the value.
    """
    PRICE_CENTS = ' ¢/kWh'
    PRICE_DOLLARS = ' $/kWh'
    VOLTS = ' V'
    AMPS = ' A'
    WATTS = ' W'
    KILOWATTS = ' kW'
    WATT_HOURS = ' Wh'
    KILOWATT_HOURS = ' kWh'
    SECONDS = ' seconds'
    MINUTES = ' minutes'
    HOURS = ' hours'
    PERCENT = '%'
    DEGREES = '°'
    CELSIUS = '°C'


def _seconds(s: float) -> timedelta:
    return timedelta(seconds=s)


def _minutes(m: float) -> timedelta:
    return timedelta(minutes=m)


def _hours(h: float) -> timedelta:
    return timedelta(hours=h)


class Constants:
    """
    Define timing, cache, logging, and display constants for Solala.

    These values control the behaviour of the control loop and GUI and are
    intended to be modified only by developers for testing or debugging.

    Timing values use seconds unless their names or comments specify minutes
    or hours.
    """

    APP_NAME: str = 'Solala'
    APP_SUBTITLE: str = 'Home Power Management'

    LOOP_TIME: timedelta = _seconds(5)  # target duration for each loop iteration - should be a factor of 1 minute
    LOOP_MIN_SLEEP_TIME: timedelta = _seconds(1)  # minimum sleep time for each loop iteration
    CONTROL_DURATION: int = 11  # number of seconds a control remains active
    DATABASE_LOG_LOOP_TIME: timedelta = _minutes(5)  # target duration for each loop iteration - should be a factor of 1 hour

    PRICE_SETTLE_CHECK: timedelta = _seconds(9)  # check delay to see if the power price has settled
    PRICE_OLD: timedelta = _minutes(5)  # duration a price forecast is valid

    PRICE_FORECAST_DURATION: timedelta = _hours(18)  # how many hours into the future to forecast price
    PRICE_FORECAST_YOUNG: timedelta = _minutes(5)  # time duration a price forecast cache is fresh
    PRICE_FORECAST_OLD: timedelta = _hours(1)  # time duration a price forecast cache is valid

    PRICE_DEMAND_WINDOW_YOUNG: timedelta = _hours(1)  # time duration a price demand window cache is fresh
    PRICE_DEMAND_WINDOW_OLD: timedelta = _hours(12)  # time duration a price demand window cache is valid

    SOLAR_FORECAST_YOUNG: timedelta = _hours(1)  # time duration a solar forecast is valid
    SOLAR_FORECAST_OLD: timedelta = _hours(3)  # time duration a solar forecast is valid

    MAX_LOG_HISTORY: int = 1000  # Maximum number of log lines in the GUI log
    BUY_PRICE_AMBER: float = 20  # Buy price threshold for amber colour
    BUY_PRICE_RED: float = 40  # Buy price threshold for red colour

    CONTROLS_ENABLED: bool = True  # Whether to present the control buttons or not - GUI only!
    ANIMATE_WEATHER_ICONS: bool = True  # Whether to animate weather icons or not
    INFOGRAPHIC_INCLUDE_RENEWABLES: bool = False  # Whether to show % renewables or not

    @staticmethod
    def to_json() -> JSONDict:
        """
        Export the application constants as a JSON-compatible dictionary.

        Returns:
            A mapping of constant names to their values.
        """
        return to_json(Constants)
