from solala.utils.json import JSONDict


class Constants:
    """
    These constants control the behaviour of the control loop.
    They should only be modified by developers for testing and debugging.
    """
    LOOP_TIME: int = 5  # number of seconds for each loop iteration
    MIN_SLEEP_TIME: int = 2  # number of seconds to sleep for each loop iteration
    CONTROL_DURATION: int = 11  # number of seconds a control remains active
    PRICE_SETTLE_CHECK: int = 10  # check delay to see if the power price has settled
    PRICE_FORECAST_DURATION = 24  # in hours

    @staticmethod
    def as_dict() -> JSONDict:
        return {
            'LOOP_TIME': Constants.LOOP_TIME,
            'MIN_SLEEP_TIME': Constants.MIN_SLEEP_TIME,
            'CONTROL_DURATION': Constants.CONTROL_DURATION,
            'PRICE_SETTLE_CHECK': Constants.PRICE_SETTLE_CHECK,
        }
