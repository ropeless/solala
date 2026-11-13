from solala.utils.json_extras import JSONContainer


class ControlLoopError(RuntimeError):

    def __init__(self, detail: str, errors: JSONContainer | None = None):
        super().__init__(detail)
        self.detail: str = detail
        self.errors: JSONContainer | None = errors
