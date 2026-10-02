from typing import Optional

from solala.utils.json import JSONContainer


class ControlLoopError(RuntimeError):

    def __init__(self, detail: str, errors: Optional[JSONContainer] = None):
        super().__init__(detail)
        self.detail: str = detail
        self.errors: Optional[JSONContainer] = errors
