from solala.delegates.power_consumer.power_consumer import PowerConsumer, ConsumerStatus
from solala.registers import RegisterBank, CallRegister


class DummyPowerConsumer(PowerConsumer):
    """
    Simulated power consumer with configurable electrical status.

    The public `status` attribute can be updated after construction
    (with care) to change the voltage, current, and power reported by the consumer.
    """

    def __init__(
            self,
            voltage: float = 240,
            current: float = 0,
            power: float | None = None,
    ) -> None:
        """
        Initialise the simulated consumer.

        Args:
            voltage: Supply voltage in volts.
            current: Current draw in amperes.
            power: Active power in watts. Defaults to voltage multiplied by
                current when omitted. If not None, then must be <= voltage * current.

        Raises:
            ValueError: If power exceeds voltage multiplied by current.
        """
        if power is None:
            power = voltage * current
        if power > voltage * current:
            raise ValueError('power > voltage * current')

        self.status = ConsumerStatus(
            voltage=voltage,
            current=current,
            power=power,
        )
        self._register_bank = RegisterBank({
            'voltage': CallRegister(lambda: self.status.voltage, float),
            'current': CallRegister(lambda: self.status.current, float),
            'power': CallRegister(lambda: self.status.power, float),
        })

    async def get_registers(self) -> RegisterBank:
        return self._register_bank

    async def get_status(self) -> ConsumerStatus:
        return self.status

    def get_connection_info(self) -> dict[str, int | float | str]:
        return {
            'connection': self.__class__.__name__,
            'voltage': self.status.voltage,
            'current': self.status.current,
            'power': self.status.power,
        }

    async def close(self) -> None:
        # nothing to do
        pass
