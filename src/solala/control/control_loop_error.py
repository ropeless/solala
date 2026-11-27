from solala.utils.json_extras import JSONContainer


class ControlLoopError(RuntimeError):
    """
    Raised when the control loop encounters an error.

    Attributes:
        detail: Description of the control-loop error.
        errors: Optional structured details about one or more underlying errors.
    """

    def __init__(self, detail: str, errors: JSONContainer | None = None):
        """
        Initialise the control-loop error.

        Args:
            detail: Description of the error.
            errors: Optional structured details about underlying errors.
        """
        super().__init__(detail)
        self.detail: str = detail
        self.errors: JSONContainer | None = errors
