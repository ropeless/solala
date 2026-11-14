from dataclasses import dataclass

from solala.utils.json_extras import JSONDict, to_json


@dataclass(frozen=True)
class ConsumerStatus:
    """
    Represents the electrical status of a power consumer.

    Attributes:
        voltage: The measured voltage in volts.
        current: The measured current in amperes.
        power: The active power in watts, measured where available or estimated
            where the device does not provide a direct measurement.
    """

    voltage: float
    current: float
    power: float

    def to_json(self) -> JSONDict:
        """
        Convert the status to a JSON-compatible dictionary.

        Returns:
            The status represented as a JSON-compatible dictionary.
        """
        return to_json(self)
