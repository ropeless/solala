from enum import auto

from solala.utils.dummy_failure import DummyFailure, FailureLocation as BaseFailureLocation, maybe_inject_failure, async_maybe_inject_failure
from solala.delegates.power_consumer.power_consumer import PowerConsumer, ConsumerStatus
from solala.register import CallRegister
from solala.register_bank import RegisterBank


class FailureLocation(BaseFailureLocation):
    """
    Operations supporting simulated power consumer failures.
    """

    get_registers = auto()
    get_status = auto()
    get_connection_info = auto()

    def is_async(self) -> bool:
        """
        Return whether the selected operation is asynchronous.
        """
        return self != FailureLocation.get_connection_info

class DummyPowerConsumer(PowerConsumer):
    """
    Simulated power consumer with configurable electrical status.

    Voltage, current, power, and on can be changed after construction.
    Callers must keep voltage, current, and power consistent: changing voltage
    does not adjust power, and changing current from zero does not restore a
    previously zero power value. The power setter validates the relationship
    power <= voltage * current when explicitly assigned.
    """

    def __init__(
            self,
            voltage: float = 240,
            current: float = 0,
            power: float | None = None,
            on: bool = True,
            *,
            failure: DummyFailure | None = None,
    ) -> None:
        """
        Initialise the simulated consumer.

        Args:
            power: Active power in watts. Defaults to voltage multiplied by
                current when omitted. If not None, then must be <= voltage * current.
            voltage: Supply voltage in volts.
            current: Current draw in amperes.
            on: Is the device switched on. Defaults to True.
            failure: Optional simulated failure configuration.

        Raises:
            ValueError: If power is negative or exceeds voltage multiplied by current.
        """
        self.failure = failure
        self._voltage: float = 0
        self._current: float = 0
        self._power: float = 0

        self.on: bool = on
        self.voltage = voltage
        self.current = current
        self.power = power

        self._register_bank = RegisterBank({
            'on': CallRegister(lambda: self.on, bool),
            'power': CallRegister(lambda: self.power, float),
            'voltage': CallRegister(lambda: self.voltage, float),
            'current': CallRegister(lambda: self.current, float),
        })

    @property
    def voltage(self) -> float:
        return self._voltage

    @voltage.setter
    def voltage(self, value: float) -> None:
        if value < 0:
            raise ValueError('voltage < 0')
        self._voltage = value

    @property
    def current(self) -> float:
        if self.on:
            return self._current
        else:
            return 0

    @current.setter
    def current(self, value: float) -> None:
        if value < 0:
            raise ValueError('current < 0')
        if self._current > 0:
            self._power *= value / self._current
        self._current = value

    @property
    def power(self) -> float:
        if self.on:
            return self._power
        else:
            return 0

    @power.setter
    def power(self, value: float | None) -> None:
        if value is None:
            value = self.voltage * self._current
        if value < 0:
            raise ValueError('power < 0')
        if value > self.voltage * self._current:
            raise ValueError('power > voltage * current')

        self._power = value

    async def get_registers(self) -> RegisterBank:
        await async_maybe_inject_failure(FailureLocation.get_registers, self.failure)
        return self._register_bank

    async def get_status(self) -> ConsumerStatus:
        await async_maybe_inject_failure(FailureLocation.get_status, self.failure)
        return ConsumerStatus(
            voltage=self.voltage,
            current=self.current,
            power=self.power,
            on=self.on,
        )

    def get_connection_info(self) -> dict[str, int | float | str]:
        maybe_inject_failure(FailureLocation.get_connection_info, self.failure)
        return {
            'connection': self.__class__.__name__,
            'on': self.on,
            'power': self._power,
            'voltage': self._voltage,
            'current': self._current,
        }

    async def close(self) -> None:
        # nothing to do
        pass
