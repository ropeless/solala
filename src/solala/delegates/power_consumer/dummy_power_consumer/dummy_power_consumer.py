from solala.delegates.power_consumer.power_consumer import PowerConsumer, ConsumerStatus
from solala.registers import RegisterBank, CallRegister


class DummyPowerConsumer(PowerConsumer):

    def __init__(
            self,
            voltage: float = 240,
            current: float = 0,
    ) -> None:
        self.status = ConsumerStatus(
            voltage=voltage,
            current=current
        )
        self._register_bank = RegisterBank({
            'voltage': CallRegister(lambda: self.status.voltage, float),
            'current': CallRegister(lambda: self.status.current, float),
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
        }

    async def close(self) -> None:
        # nothing to do
        pass
