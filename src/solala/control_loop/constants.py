from solala.utils.json import JSONDict


class Constants:
    """
    These constants control the behaviour of the control loop.
    They should only be modified by developers for testing and debugging.
    """
    LOOP_TIME: int = 5  # number of seconds for each loop iteration
    MIN_SLEEP_TIME: int = 2  # number of seconds to sleep for each loop iteration
    CONTROL_DURATION: int = 11  # number of seconds a control remains active
    PRICE_LOOK_AHEAD: int = 60  # number of minutes to look ahead (should be a multiple of 5)
    DISABLE_FEED_IN_TOLERANCE: float = 2.0  # cents, a feed-in power price tolerance for price lookahead
    ENABLE_FEED_IN_TOLERANCE: float = 2.0  # cents, a feed-in power price tolerance for price lookahead
    STOP_BUY_TOLERANCE: float = 2.0  # cents, a buy power price tolerance for price lookahead
    START_BUY_TOLERANCE: float = 2.0  # cents, a buy power price tolerance for price lookahead

    @staticmethod
    def as_dict() -> JSONDict:
        return {
            'LOOP_TIME': Constants.LOOP_TIME,
            'MIN_SLEEP_TIME': Constants.MIN_SLEEP_TIME,
            'CONTROL_DURATION': Constants.CONTROL_DURATION,
            'PRICE_LOOK_AHEAD': Constants.PRICE_LOOK_AHEAD,
            'DISABLE_FEED_IN_TOLERANCE': Constants.DISABLE_FEED_IN_TOLERANCE,
            'ENABLE_FEED_IN_TOLERANCE': Constants.ENABLE_FEED_IN_TOLERANCE,
            'STOP_BUY_TOLERANCE': Constants.STOP_BUY_TOLERANCE,
            'START_BUY_TOLERANCE': Constants.START_BUY_TOLERANCE,
        }
