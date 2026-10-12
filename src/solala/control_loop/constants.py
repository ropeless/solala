from solala.utils.json import JSONDict


class Constants:
    """
    These constants control the behaviour of the control loop.
    They should only be modified by developers for testing and debugging.
    """
    LOOP_TIME: int = 5  # number of seconds for each loop iteration
    MIN_SLEEP_TIME: int = 2  # number of seconds to sleep for each loop iteration
    CONTROL_DURATION: int = 11  # number of seconds a control remains active
    PRICE_SETTLE_CHECK: int = 9  # check delay to see if the power price has settled
    PRICE_FORECAST_DURATION = 13  # in hours
    PRICE_FORECAST_AGE = 5  # number of minutes a price forecast is valid
    SOLAR_FORECAST_AGE = 4 * 60  # number of minutes a solar forecast is valid

    @staticmethod
    def as_dict() -> JSONDict:
        return {
            'LOOP_TIME': Constants.LOOP_TIME,
            'MIN_SLEEP_TIME': Constants.MIN_SLEEP_TIME,
            'CONTROL_DURATION': Constants.CONTROL_DURATION,
            'PRICE_SETTLE_CHECK': Constants.PRICE_SETTLE_CHECK,
            'PRICE_FORECAST_DURATION': Constants.PRICE_FORECAST_DURATION,
        }
