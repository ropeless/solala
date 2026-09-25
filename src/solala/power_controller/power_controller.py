from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Iterable, Tuple

from solala.utils.json import JSONDict


@dataclass
class PowerStatus:
    state_of_charge: float
    battery_status: str
    grid_status: str
    power_limit: float
    grid_power: float
    solar_power: float
    battery_power: float
    house_power: float

    def as_dict(self) -> JSONDict:
        return {
            'state_of_charge': self.state_of_charge,
            'battery_status': self.battery_status,
            'grid_status': self.grid_status,
            'power_limit': self.power_limit,
            'grid_power': self.grid_power,
            'solar_power': self.solar_power,
            'battery_power': self.battery_power,
            'house_power': self.house_power,
        }


class PowerController(ABC):
    """
    High-level power power_controller to send commands and read status from the power system.
    """

    @abstractmethod
    def close(self) -> None:
        """
        Close any connections to the power system.
        """
        ...

    @abstractmethod
    def get_registers(self) -> Iterable[Tuple[str, int | float | str]]:
        """
        Get the values of all known registers.
        """
        ...

    @abstractmethod
    def get_status(self) -> PowerStatus:
        """
        Get a high-level status of the system.
        """
        ...

    # =================================================
    #  Battery Control
    # =================================================

    @abstractmethod
    def enable_battery(self) -> None:
        """
        Allow the battery to charge and discharge.
        This is the normal state.
        """
        ...

    @abstractmethod
    def disable_battery(self) -> None:
        """
        Stop the battery from charging and discharging.
        """
        ...

    @abstractmethod
    def force_charge(self) -> None:
        """
        Force the battery to charge.
        This will aim to charge the battery to its maximum capacity,
        even if it means drawing from the grid.
        """
        ...

    @abstractmethod
    def force_discharge(self) -> None:
        """
        Force the battery to discharge.
        This is a way to force stored power to the grid.
        """
        ...

    # =================================================
    #  Inverter Control
    # =================================================

    @abstractmethod
    def enable_inverter(self) -> None:
        """
        Don't put any limit on inverter output power, so there is no limit on exports.
        This is the normal state.
        """
        ...

    @abstractmethod
    def disable_inverter(self, *, change_duration: int) -> None:
        """
        Stop the inverter providing output power.
        """
        ...

    @abstractmethod
    def zero_export(self, *, change_duration: int) -> None:
        """
        Limit inverter output power to balance consumption, so there is no export.
        Will still allow drawing from the grid if insufficient solar supply for demand.
        This may need to be repeatedly called as the consumption may change,
        or the change duration expires.

        Args:
            change_duration: The duration in seconds to disable the export.
        """
        ...
