from dataclasses import dataclass

from solala.utils.json_extras import JSONDict, to_json


@dataclass(frozen=True)
class ConsumerStatus:
    """
    Represents the electrical status of a power consumer.

    Attributes:
        on: Whether the consumer device is switched on or not.
        voltage: The measured voltage in volts.
        current: The measured current in amperes.
        power: The active power in watts, measured where available or estimated
            where the device does not provide a direct measurement.
        accumulated_energy: Accumulated energy used from some arbitrary start time, in Wh;
            or None if it cannot be provided by the device.

    """

    on: bool
    power: float
    voltage: float
    current: float
    accumulated_energy: float | None

    def to_json(self) -> JSONDict:
        """
        Convert the status to a JSON-compatible dictionary.

        Returns:
            The status represented as a JSON-compatible dictionary.
        """
        return to_json(self)
