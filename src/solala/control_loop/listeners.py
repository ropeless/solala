from abc import ABC, abstractmethod
from typing import final, Dict

from solala import control_loop
from solala.utils.json import JSONDict


class StatusListener(ABC):
    """
    Abstract base class for status listeners.
    System status is provided to the listeners once per iteration through the control loop.
    """

    @abstractmethod
    def update(self, status_json: JSONDict) -> None:
        ...

    @final
    def update_now(self) -> None:
        """
        Manual update.
        """
        self.update(control_loop.get_status())


class RegistersListener(ABC):
    """
    Abstract base class for status listeners.
    Registers are provided to the listeners once per iteration through the control loop.
    """

    @abstractmethod
    def update(self, register_values: Dict[str, int | float | str | bool]) -> None:
        ...

    @final
    def update_now(self) -> None:
        """
        Manual update.
        """
        self.update(control_loop.get_registers())
