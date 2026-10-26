from solala.utils.json import JSONDict, to_json

APP_NAME: str = 'Solala'
APP_SUBTITLE: str = 'Home Power Management'

TIMESTAMP_FORMAT = '%Y-%m-%d %H:%M:%S (%Z)'  # format for human-readable timestamps
GUI_DATE_FORMAT = '%a, %d %b %Y'
GUI_TIME_FORMAT = '%H:%M'


DEFAULT_DISABLE_FEED_IN_PRICE_THRESHOLD: float = -0.1  # disable export below this price
DEFAULT_ENABLE_FEED_IN_PRICE_THRESHOLD: float = 0.1  # re-enable export above this price
DEFAULT_START_CHARGE_PRICE_THRESHOLD: float = 10  # start force charging below this price
DEFAULT_STOP_CHARGE_PRICE_THRESHOLD: float = 11  # stop force charging above this price

DEFAULT_INVERTER_EFFICIENCY: float = 0.96  # as a fraction (0 to 1)
DEFAULT_INVERTER_LIMIT: float = float('inf')  # in Watts
DEFAULT_TEMPERATURE_COEFFICIENT: float = -0.004  # in Celsius


class Constants:
    """
    These constants control the behaviour of the control loop and GUI.
    They should only be modified by developers for testing and debugging.
    """

    LOOP_TIME: int = 5  # number of seconds for each loop iteration
    LOOP_MIN_SLEEP_TIME: int = 1  # number of seconds to sleep for each loop iteration
    CONTROL_DURATION: int = 11  # number of seconds a control remains active
    PRICE_SETTLE_CHECK: int = 9  # check delay to see if the power price has settled
    PRICE_FORECAST_DURATION = 13  # in hours
    PRICE_FORECAST_AGE = 5  # number of minutes a price forecast is valid
    SOLAR_FORECAST_AGE = 3 * 60  # number of minutes a solar forecast is valid

    MAX_LOG_HISTORY: int = 1000  # Maximum number of log lines in the GUI log
    BUY_PRICE_AMBER = 20  # Buy price threshold for amber colour
    BUY_PRICE_RED = 40  # Buy price threshold for red colour

    CONTROLS_ENABLED: bool = False  # Whether to present the control buttons or not
    ANIMATE_WEATHER_ICONS: bool = True  # Whether to animate weather icons or not
    INFOGRAPHIC_INCLUDE_RENEWABLES: bool = False  # Whether to show % renewables or not

    @staticmethod
    def to_json() -> JSONDict:
        return to_json(Constants)
