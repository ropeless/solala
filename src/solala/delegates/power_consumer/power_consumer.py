from abc import ABC, abstractmethod
from dataclasses import dataclass
from types import TracebackType
from typing import Self

from solala.registers import RegisterBank
from solala.utils.json_extras import JSONDict, to_json


@dataclass(frozen=True)
class ConsumerStatus:
    voltage: float
    current: float

    @property
    def power(self) -> float:
        return self.voltage * self.current

    def to_json(self) -> JSONDict:
        return to_json(self)


class PowerConsumer(ABC):
    """
    High-level interface to query an instrumented power consumption device.
    """

    @abstractmethod
    async def get_registers(self) -> RegisterBank:
        """
        Get the values of all known registers.
        """
        ...

    @abstractmethod
    async def get_status(self) -> ConsumerStatus:
        """
        Get the status of the consumer.
        """
        ...

    @abstractmethod
    def get_connection_info(self) -> JSONDict:
        """
        Get information about the connection.
        """
        ...

    @abstractmethod
    async def close(self) -> None:
        """
        Close any connections to the consumer.
        """
        ...

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.close()
