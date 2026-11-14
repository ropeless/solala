from abc import ABC, abstractmethod
from dataclasses import dataclass
from types import TracebackType
from typing import Self

from solala.registers import RegisterBank
from solala.utils.json_extras import JSONDict, to_json


@dataclass(frozen=True)
class ConsumerStatus:
    """
    Represents the electrical status of a power consumer.

    Attributes:
        voltage: The measured voltage in volts.
        current: The measured current in amperes.
    """

    voltage: float
    current: float

    @property
    def power(self) -> float:
        """
        Return the calculated power consumption in watts.
        """
        return self.voltage * self.current

    def to_json(self) -> JSONDict:
        """
        Convert the status to a JSON-compatible dictionary.

        Returns:
            The status represented as a JSON-compatible dictionary.
        """
        return to_json(self)


class PowerConsumer(ABC):
    """
    High-level interface for monitoring an instrumented power consumer.

    Implementations provide access to device registers, current status,
    connection information, and connection cleanup.
    """

    @abstractmethod
    async def get_registers(self) -> RegisterBank:
        """
        Get the registers exposed by the consumer.

        Returns:
            A register bank containing the consumer's registers.
        """
        ...

    @abstractmethod
    async def get_status(self) -> ConsumerStatus:
        """
        Get the current electrical status of the consumer.

        Returns:
            The consumer's voltage and current measurements.
        """
        ...

    @abstractmethod
    def get_connection_info(self) -> JSONDict:
        """
        Get information about the consumer connection.

        Returns:
            A JSON-compatible dictionary containing connection information.
        """
        ...

    @abstractmethod
    async def close(self) -> None:
        """
        Close any connections or resources held by the consumer.
        """
        ...

    async def __aenter__(self) -> Self:
        """
        Enter the asynchronous context manager.

        Returns:
            This consumer instance.
        """
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """
        Exit the asynchronous context manager and close the consumer.
        """
        await self.close()
