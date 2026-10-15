from solala.utils.json import JSONDict, to_json

APP_NAME: str = 'Solala'
APP_SUBTITLE: str = 'Home Power Management'

DATE_FORMAT = '%Y-%m-%d %H:%M:%S (%Z)'  # format for human-readable timestamps


class Constants:
    """
    These constants control the behaviour of the control loop.
    They should only be modified by developers for testing and debugging.
    """

    LOOP_TIME: int = 5  # number of seconds for each loop iteration
    LOOP_MIN_SLEEP_TIME: int = 2  # number of seconds to sleep for each loop iteration
    CONTROL_DURATION: int = 11  # number of seconds a control remains active
    PRICE_SETTLE_CHECK: int = 9  # check delay to see if the power price has settled
    PRICE_FORECAST_DURATION = 13  # in hours
    PRICE_FORECAST_AGE = 5  # number of minutes a price forecast is valid
    SOLAR_FORECAST_AGE = 3 * 60  # number of minutes a solar forecast is valid

    MAX_LOG_HISTORY: int = 1000
    BUY_PRICE_AMBER = 20
    BUY_PRICE_RED = 40

    CONTROLS_ENABLED: bool = True

    @staticmethod
    def to_json() -> JSONDict:
        return to_json(Constants)
