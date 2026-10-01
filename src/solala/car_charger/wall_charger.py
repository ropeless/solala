from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Iterable, Tuple, Dict


@dataclass(frozen=True)
class ChargerStatus:
    voltage: float
    current: float

    @property
    def power(self) -> float:
        return self.voltage * self.current

    def as_dict(self) -> Dict[str, float]:
        return {
            'voltage': self.voltage,
            'current': self.current,
            'power': self.power,
        }


class CarCharger(ABC):
    """
    High-level car charger to send commands and read status from the car charger.
    """

    @abstractmethod
    def get_status(self) -> ChargerStatus:
        """
        Get the status of the charger.
        """
        ...

    @abstractmethod
    def get_registers(self) -> Iterable[Tuple[str, int | float | str | bool]]:
        """
        Get the values of all known registers.
        """
        ...

    @abstractmethod
    def close(self) -> None:
        """
        Close any connections to the car charger.
        """
        ...

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return exc_type is None
