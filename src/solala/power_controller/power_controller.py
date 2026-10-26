from abc import ABC, abstractmethod
from dataclasses import dataclass, asdict
from typing import Iterable, Tuple

from solala.utils.json import JSONDict


@dataclass
class PowerStatus:
    state_of_charge: float
    power_limit: float
    grid_power: float
    solar_power: float
    battery_power: float
    house_power: float

    def to_json(self) -> JSONDict:
        return asdict(self)


class PowerController(ABC):
    """
    High-level power controller to send commands and read status from the power system.
    """

    @abstractmethod
    async def close(self) -> None:
        """
        Close any connections to the power system.
        """
        ...

    # =================================================
    #  Power controller status
    # =================================================

    @abstractmethod
    async def get_registers(self) -> Iterable[Tuple[str, int | float | str]]:
        """
        Get the values of all known registers.
        """
        ...

    @abstractmethod
    async def get_status(self) -> PowerStatus:
        """
        Get the high-level status of the system.
        """
        ...

    @abstractmethod
    def get_connection_status(self) -> JSONDict:
        """
        Get the status of the connection.
        """
        ...

    @abstractmethod
    def get_inverter_limit(self) -> float:
        """
        Get the reported power limit on inverter AC output.
        This is expected to stay constant for the lifetime of the connection.
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

    @abstractmethod
    def charge_only(self) -> None:
        """
        Allow the battery to charge (when there is excess solar power)
        but do not allow the battery to discharge (when there is insufficient solar power).
        If there is insufficient solar power, power will be drawn from the grid.
        """
        ...

    @abstractmethod
    def discharge_only(self) -> None:
        """
        Allow the battery to discharge (when there is insufficient solar power)
        but do not allow the battery to charge (when there is an oversupply of solar power).
        If there is an oversupply of solar power, power will be sent to the grid.
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

        This inverter mode may be auto-reverting, but the control loop is requesting
        that it not revert for at least `change_duration` seconds.

        Args:
            change_duration: the expected minimum auto-revert duration in seconds.
        """
        ...

    @abstractmethod
    def zero_export(self, *, change_duration: int) -> None:
        """
        Limit inverter output power to balance consumption, so there is no export.
        Will still allow drawing from the grid if insufficient solar supply for demand.

        This inverter mode may be auto-reverting, but the control loop is requesting
        that it not revert for at least `change_duration` seconds.

        This may also need to be repeatedly called as the consumption may change,
        or the change duration expires.

        Args:
            change_duration: the expected minimum auto-revert duration in seconds.
        """
        ...
