from typing import Iterable, Tuple, Dict

from solala.power_consumer.power_consumer import PowerConsumer, ConsumerStatus


class DummyPowerConsumer(PowerConsumer):

    def __init__(
            self,
            voltage: float = 240,
            current: float = 0,
    ):
        self.status = ConsumerStatus(
            voltage=voltage,
            current=current
        )

    def get_status(self) -> ConsumerStatus:
        return self.status

    def get_connection_status(self) -> Dict[str, int | float | str]:
        return {
            'status': 'Dummy connection',
            'voltage': self.status.voltage,
            'current': self.status.current,
        }

    def get_registers(self) -> Iterable[Tuple[str, int | float | str | bool]]:
        return self.get_connection_status().items()

    def close(self) -> None:
        # nothing to do
        pass
