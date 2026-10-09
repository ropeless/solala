from typing import Iterable, Tuple

from solala.power_consumer.power_consumer import PowerConsumer, ConsumerStatus


class DummyPowerConsumer(PowerConsumer):

    def __init__(self):
        self.status = ConsumerStatus(
            voltage=240,
            current=0
        )

    def get_status(self) -> ConsumerStatus:
        return self.status

    def get_registers(self) -> Iterable[Tuple[str, int | float | str | bool]]:
        return (
            ('consumer', 'dummy'),
            ('voltage', self.status.voltage),
            ('current', self.status.current),
        )

    def close(self) -> None:
        # nothing to do
        pass
