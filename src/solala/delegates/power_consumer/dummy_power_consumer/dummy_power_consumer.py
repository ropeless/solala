from enum import auto
from time import monotonic

from solala.delegates.power_consumer.power_consumer import PowerConsumer, ConsumerStatus, SwitchRegister
from solala.register import CallRegister
from solala.register_bank import RegisterBank
from solala.utils.dummy_failure import DummyFailure, FailureLocation as BaseFailureLocation, maybe_inject_failure, \
    async_maybe_inject_failure, get_dummy_failure_info
from solala.utils.json_extras import JSONDict


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
    Energy is accumulated using elapsed monotonic time and the active power
    before each state change. When current changes, active power is adjusted
    to preserve the existing power factor.
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
            can_switch: bool = True,
            include_accumulated_energy: bool = True,
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
            can_switch: Whether the simulated consumer supports switching.
            include_accumulated_energy: Whether to expose accumulated energy in Wh.

        Raises:
            ValueError: If power is negative or exceeds voltage multiplied by current.
        """
        super().__init__(can_switch)
        self._include_accumulated_energy = include_accumulated_energy

        self.failure = failure
        self._voltage: float = 0
        self._current: float = 0
        self._power: float = 0
        self._power_factor: float = 1
        self._energy: float = 0
        self._create_time = monotonic()
        self._time: float = self._create_time
        self._on: bool = on

        self.voltage: float = voltage
        self.current: float = current
        self.power: float | None = power

        self._register_bank = RegisterBank({
            'power': CallRegister(lambda: self.power, float),
            'voltage': CallRegister(lambda: self.voltage, float),
            'current': CallRegister(lambda: self.current, float),
            'energy': CallRegister(lambda: self.energy, float),
            'uptime': CallRegister(lambda: self.uptime, float),
            'switch': SwitchRegister(self),
        })

    @property
    def voltage(self) -> float:
        return self._voltage

    @voltage.setter
    def voltage(self, value: float) -> None:
        if value < 0:
            raise ValueError('voltage < 0')
        self._check_energy()
        self._voltage = value

    @property
    def current(self) -> float:
        if self._on:
            return self._current
        else:
            return 0

    @current.setter
    def current(self, value: float) -> None:
        if value < 0:
            raise ValueError('current < 0')
        self._check_energy()
        if self._current > 0:
            self._power *= value / self._current
        self._current = value

    @property
    def power(self) -> float:
        if self._on:
            return self._power
        else:
            return 0

    @power.setter
    def power(self, value: float | None) -> None:
        apparent_power = self._voltage * self._current

        if value is None:
            value = apparent_power * self._power_factor
        if value < 0:
            raise ValueError('power < 0')
        if value > apparent_power:
            raise ValueError('power > voltage * current')

        self._check_energy()
        self._power = value
        self._power_factor = value / apparent_power if apparent_power > 0 else 1

    @property
    def energy(self) -> float:
        self._check_energy()
        return self._energy

    @property
    def uptime(self) -> float:
        return monotonic() - self._create_time

    async def get_registers(self) -> RegisterBank:
        await async_maybe_inject_failure(FailureLocation.get_registers, self.failure)
        return self._register_bank

    async def get_status(self) -> ConsumerStatus:
        await async_maybe_inject_failure(FailureLocation.get_status, self.failure)
        self._check_energy()
        return ConsumerStatus(
            voltage=self.voltage,
            current=self.current,
            power=self.power,
            on=self._on,
            accumulated_energy=self._energy if self._include_accumulated_energy else None,
        )

    def get_connection_info(self) -> JSONDict:
        maybe_inject_failure(FailureLocation.get_connection_info, self.failure)
        return {
            'connection': self.__class__.__name__,
            'on': self._on,
            'power': self._power,
            'voltage': self._voltage,
            'current': self._current,
            'can_switch': self.can_switch,
            'include_accumulated_energy': self._include_accumulated_energy,
            'failure': get_dummy_failure_info(self.failure),
            'create_time': self._create_time,
        }

    async def close(self) -> None:
        # nothing to do
        pass

    async def _get_switch(self) -> bool:
        return self._on

    async def _set_switch(self, on: bool) -> None:
        self._check_energy()
        self._on = on

    def _check_energy(self) -> None:
        """
        Accumulate the energy of the power consumer since the last timestamp.
        """
        now = monotonic()
        duration = (now - self._time) / 3600  # in hours
        self._time = now
        self._energy += duration * self.power  # in Wh.
