from abc import ABC, abstractmethod
from dataclasses import dataclass, asdict
from types import TracebackType
from typing import Self

from solala.registers import RegisterBank
from solala.utils.json_extras import JSONDict


@dataclass
class PowerStatus:
    """
    Records the current operating status and accumulated energy of the power system.

    Attributes:
        state_of_charge: Battery state of charge as a percentage.
        power_limit: Inverter output power limit as a percentage of rated capacity.
        grid_power: Power imported from the grid in watts; negative values indicate export.
        solar_power: Solar generation in watts.
        battery_power: Battery power in watts; positive values indicate charging and
            negative values indicate discharging.
        house_power: House consumption in watts.
        accumulated_solar_energy: Accumulated solar generation in watt-hours.
        accumulated_grid_energy_import: Accumulated energy imported from the grid
            in watt-hours.
        accumulated_grid_energy_export: Accumulated energy exported to the grid
            in watt-hours.
        accumulated_battery_energy_charge: Accumulated energy used to charge the
            battery in watt-hours.
        accumulated_battery_energy_discharge: Accumulated energy discharged from
            the battery in watt-hours.
    """

    state_of_charge: float
    power_limit: float

    grid_power: float
    solar_power: float
    battery_power: float
    house_power: float

    accumulated_solar_energy: float
    accumulated_grid_energy_import: float
    accumulated_grid_energy_export: float
    accumulated_battery_energy_charge: float
    accumulated_battery_energy_discharge: float

    def to_json(self) -> JSONDict:
        """
        Convert the status to a JSON-compatible dictionary.

        Returns:
            The status represented as a JSON-compatible dictionary.
        """
        return asdict(self)


class PowerController(ABC):
    """
    High-level interface for monitoring and controlling the power system.

    Implementations provide access to system registers and status, battery and
    inverter controls, and connection information.
    """

    @abstractmethod
    async def close(self) -> None:
        """
        Close any connections to the power system and release associated resources.
        """
        ...

    # =================================================
    #  Power controller status
    # =================================================

    @abstractmethod
    async def get_registers(self) -> RegisterBank:
        """
        Get the register bank exposed by the power controller.

        Returns:
            The register bank containing the available system registers.
        """
        ...

    @abstractmethod
    async def get_status(self) -> PowerStatus:
        """
        Get the current high-level status of the power system.

        Returns:
            The system status, including instantaneous power measurements and
            accumulated energy measurements.
        """
        ...

    @abstractmethod
    def get_connection_info(self) -> JSONDict:
        """
        Get information about the power controller connection.

        Returns:
            A JSON-compatible dictionary containing connection information.
        """
        ...

    @abstractmethod
    async def get_inverter_limit(self) -> float:
        """
        Get the total rated AC output power limit of the connected inverters.

        This value is expected to remain constant for the lifetime of the connection.

        Returns:
            The total inverter output limit in watts.
        """
        ...

    # =================================================
    #  Battery Control
    # =================================================

    @abstractmethod
    async def enable_battery(self) -> None:
        """
        Allow the battery to charge and discharge.
        This is the normal operating mode.
        """
        ...

    @abstractmethod
    async def disable_battery(self) -> None:
        """
        Prevent the battery from charging or discharging.
        """
        ...

    @abstractmethod
    async def force_charge(self) -> None:
        """
        Force the battery to charge towards its maximum state of charge.

        The battery may draw power from the grid if solar generation is insufficient.
        """
        ...

    @abstractmethod
    async def force_discharge(self) -> None:
        """
        Force the battery to discharge, allowing stored energy to be exported to the grid.
        """
        ...

    @abstractmethod
    async def charge_only(self) -> None:
        """
        Allow the battery to charge from excess solar generation, but prevent it
        from discharging.

        If solar generation is insufficient to meet house demand, power is drawn
        from the grid.
        """
        ...

    @abstractmethod
    async def discharge_only(self) -> None:
        """
        Allow the battery to discharge when solar generation is insufficient, but
        prevent it from charging.

        Any excess solar generation is exported to the grid.
        """
        ...

    # =================================================
    #  Inverter Control
    # =================================================

    @abstractmethod
    async def enable_inverter(self) -> None:
        """
        Remove the inverter output power limit.

        This is the normal operating mode and allows the inverters to generate
        up to their available output capacity.
        """
        ...

    @abstractmethod
    async def disable_inverter(self, *, change_duration: int) -> None:
        """
        Stop the inverters from supplying output power.

        The inverter setting may revert automatically. The controller requests
        that the setting remain in effect for at least the specified duration.

        Args:
            change_duration: Minimum requested duration, in seconds, before the
                inverter setting automatically reverts.
        """
        ...

    @abstractmethod
    async def zero_export(self, *, change_duration: int) -> None:
        """
        Limit inverter output power to match consumption, preventing power export
        to the grid.

        The system may still import power from the grid when solar generation is
        insufficient to meet demand.

        The inverter setting may revert automatically, and may need to be updated
        repeatedly as consumption changes or the requested duration expires.

        Args:
            change_duration: Minimum requested duration, in seconds, before the
                inverter setting automatically reverts.
        """
        ...

    async def __aenter__(self) -> Self:
        """
        Enter the asynchronous context manager.

        Returns:
            This power controller instance.
        """
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """
        Exit the asynchronous context manager and close the power controller.
        """
        await self.close()
