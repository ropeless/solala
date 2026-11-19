from abc import ABC, abstractmethod
from types import TracebackType
from typing import Self, final

from solala.delegates.power_consumer.consumer_status import ConsumerStatus
from solala.register import ReadOnlyError, Register, RegisterValue
from solala.register_bank import RegisterBank
from solala.utils.json_extras import JSONDict


class PowerConsumer(ABC):
    """
    High-level interface for monitoring an instrumented power consumer.

    Implementations provide access to device registers, current status,
    connection information, and connection clean-up.
    """

    def __init__(self, can_switch: bool) -> None:
        self._can_switch: bool = can_switch

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
            The consumer's voltage and current measurements, together with
            its active power in watts.
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

    # =================================================
    #  Switch Control
    # =================================================

    @property
    def can_switch(self) -> bool:
        return self._can_switch

    @final
    async def get_switch(self) -> bool:
        """
        Get the switch state of the consumer (on = True, off = False).
        This should be equivalent to `self.get_status.on`.
        """
        return await self._get_switch()

    @final
    async def set_switch(self, on: bool) -> None:
        """
        Set the switch state of the consumer (on = True, off = False).
        If the switch is not writeable, then
        """
        if self._can_switch:
            await self._set_switch(on)
        else:
            raise ReadOnlyError()

    @abstractmethod
    async def _get_switch(self) -> bool:
        ...

    @abstractmethod
    async def _set_switch(self, on: bool) -> None:
        ...

    # =================================================
    #  Async context manager
    # =================================================

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


class SwitchRegister(Register):
    """
    A register to expose the switch of a power consumer.

    This is a helper class for implementers of `PowerConsumer`.
    """

    def __init__(self, consumer: PowerConsumer) -> None:
        """
        Initialise the register giving access to the switch of a power consumer.

        Args:
            consumer: The power consumer.
        """
        super().__init__(bool, consumer.can_switch)
        self._consumer: PowerConsumer = consumer

    async def _get(self) -> bool:
        # noinspection PyProtectedMember
        return await self._consumer._get_switch()

    async def _set(self, value: RegisterValue) -> None:
        assert isinstance(value, bool), 'should be ensured by the parent class'
        # noinspection PyProtectedMember
        return await self._consumer._set_switch(value)
