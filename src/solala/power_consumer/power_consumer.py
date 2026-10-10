from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Iterable, Tuple, Dict

from solala.utils.json import JSONDict


@dataclass(frozen=True)
class ConsumerStatus:
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


class PowerConsumer(ABC):
    """
    High-level interface to query an instrumented power consumption device.
    """

    @abstractmethod
    def get_status(self) -> ConsumerStatus:
        """
        Get the status of the consumer.
        """
        ...

    @abstractmethod
    def get_connection_status(self) -> JSONDict:
        """
        Get the status of the connection.
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
        Close any connections to the consumer.
        """
        ...

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return exc_type is None
