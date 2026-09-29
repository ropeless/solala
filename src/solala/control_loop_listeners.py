from abc import ABC, abstractmethod
from typing import final

from solala import control_loop
from solala.utils.json import JSONDict


class StatusListener(ABC):

    @abstractmethod
    def update(self, status_json: JSONDict) -> None:
        ...

    @final
    def update_now(self) -> None:
        """
        Manual update.
        """
        status_json: JSONDict = control_loop.get_status()
        self.update(status_json)


class RegistersListener(ABC):

    @abstractmethod
    def update(self, registers_json: JSONDict) -> None:
        ...

    @final
    def update_now(self) -> None:
        """
        Manual update.
        """
        registers_json: JSONDict = control_loop.get_registers()
        self.update(registers_json)
