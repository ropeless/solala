from abc import ABC, abstractmethod
from types import TracebackType
from typing import Self

from solala.delegates.power_controller.power_status import PowerStatus
from solala.registers import RegisterBank
from solala.utils.json_extras import JSONDict


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
