from enum import Enum, auto
from functools import partial

from solala.delegates.power_controller.power_controller import PowerController, PowerStatus
from solala.register import CallRegister
from solala.register_bank import RegisterBank
from solala.utils.time_extras import now
from solala.utils.dummy_failure import DummyFailure, FailureLocation as BaseFailureLocation, maybe_inject_failure, async_maybe_inject_failure


class BatteryMode(Enum):
    """
    Operating modes supported by the dummy battery simulation.
    """

    ENABLE = auto()
    DISABLE = auto()
    FORCE_CHARGE = auto()
    FORCE_DISCHARGE = auto()
    CHARGE_ONLY = auto()
    DISCHARGE_ONLY = auto()


class InverterMode(Enum):
    """
    Operating modes supported by the dummy inverter simulation.
    """

    ENABLE = auto()
    DISABLE = auto()
    ZERO_EXPORT = auto()


class FailureLocation(BaseFailureLocation):
    """
    Operations supporting simulated power controller failures.
    """

    get_inverter_limit = auto()
    get_connection_info = auto()
    get_registers = auto()
    get_status = auto()
    enable_battery = auto()
    disable_battery = auto()
    charge_only = auto()
    discharge_only = auto()
    force_charge = auto()
    force_discharge = auto()
    enable_inverter = auto()
    disable_inverter = auto()
    zero_export = auto()

    def is_async(self) -> bool:
        """
        Return whether the selected operation is asynchronous.
        """
        return self != FailureLocation.get_connection_info


class DummyPowerController(PowerController):
    """
    A dummy power controller for testing and demonstration purposes.

    Simulates a simple power system with a fixed house load, a solar inverter,
    and a battery. The simulation updates power flows according to the selected
    battery and inverter modes and accumulates energy between updates.

    Public fields may be updated by the client at any time. Changes do not
    automatically update the simulated power flows; `update_status()` should
    be called after making changes.
    """

    def __init__(
            self,
            *,
            inverter_limit: float,
            house_power: float,
            max_charge_param: float,
            max_discharge_param: float,
            failure: DummyFailure | None = None,
    ) -> None:
        """
        Initialise a dummy power system.

        Args:
            inverter_limit: Maximum simulated inverter output power, in watts.
            house_power: Fixed simulated house load, in watts.
            max_charge_param: Maximum simulated battery charging power, in watts.
            max_discharge_param: Maximum simulated battery discharging power, in watts.
            failure: Optional simulated failure configuration.
        """
        # Disable injection while initialising registers and simulated state.
        self.failure = None
        self.state_of_charge = 50

        self.house_power = house_power
        self.power_limit = 0
        self.battery_power = 0
        self.grid_power = 0
        self.solar_power = 0
        self.battery_mode: BatteryMode = BatteryMode.ENABLE
        self.inverter_mode: InverterMode = InverterMode.ENABLE

        self.inverter_limit = inverter_limit
        self.max_charge_param = max_charge_param
        self.max_discharge_param = max_discharge_param

        self.last_accumulation: float = now().timestamp()
        self.accumulated_solar_energy: float = 0
        self.accumulated_grid_energy_import: float = 0
        self.accumulated_grid_energy_export: float = 0
        self.accumulated_battery_energy_charge: float = 0
        self.accumulated_battery_energy_discharge: float = 0

        self.registers = RegisterBank({
            key: CallRegister(partial(self._get_connection_value, key))
            for key in self.get_connection_info().keys()
        })

        self.update_status()
        self.failure = failure

    async def get_inverter_limit(self) -> float:
        await async_maybe_inject_failure(FailureLocation.get_inverter_limit, self.failure)
        return self.inverter_limit

    def get_connection_info(self) -> dict[str, int | float | str]:
        maybe_inject_failure(FailureLocation.get_connection_info, self.failure)
        return {
            'connection': self.__class__.__name__,
            'battery_mode': self.battery_mode.name,
            'inverter_mode': self.inverter_mode.name,
            'state_of_charge': self.state_of_charge,
            'power_limit': self.power_limit,
            'battery_power': self.battery_power,
            'grid_power': self.grid_power,
            'solar_power': self.solar_power,
            'house_power': self.house_power,
            'inverter_limit': self.inverter_limit,
            'max_charge_param': self.max_charge_param,
            'max_discharge_param': self.max_discharge_param,
        }

    def _get_connection_value(self, key: str) -> int | float | str:
        return self.get_connection_info()[key]

    async def get_registers(self) -> RegisterBank:
        await async_maybe_inject_failure(FailureLocation.get_registers, self.failure)
        return self.registers

    async def get_status(self) -> PowerStatus:
        await async_maybe_inject_failure(FailureLocation.get_status, self.failure)
        self.update_status()
        return PowerStatus(
            state_of_charge=self.state_of_charge,
            power_limit=self.power_limit,
            battery_power=self.battery_power,
            grid_power=self.grid_power,
            solar_power=self.solar_power,
            house_power=self.house_power,
            accumulated_solar_energy=self.accumulated_solar_energy,
            accumulated_grid_energy_import=self.accumulated_grid_energy_import,
            accumulated_grid_energy_export=self.accumulated_grid_energy_export,
            accumulated_battery_energy_charge=self.accumulated_battery_energy_charge,
            accumulated_battery_energy_discharge=self.accumulated_battery_energy_discharge,
        )

    async def enable_battery(self) -> None:
        await async_maybe_inject_failure(FailureLocation.enable_battery, self.failure)
        self.battery_mode = BatteryMode.ENABLE
        self.update_status()

    async def disable_battery(self) -> None:
        await async_maybe_inject_failure(FailureLocation.disable_battery, self.failure)
        self.battery_mode = BatteryMode.DISABLE
        self.update_status()

    async def charge_only(self) -> None:
        await async_maybe_inject_failure(FailureLocation.charge_only, self.failure)
        self.battery_mode = BatteryMode.CHARGE_ONLY
        self.update_status()

    async def discharge_only(self) -> None:
        await async_maybe_inject_failure(FailureLocation.discharge_only, self.failure)
        self.battery_mode = BatteryMode.DISCHARGE_ONLY
        self.update_status()

    async def force_charge(self) -> None:
        await async_maybe_inject_failure(FailureLocation.force_charge, self.failure)
        self.battery_mode = BatteryMode.FORCE_CHARGE
        self.update_status()

    async def force_discharge(self) -> None:
        await async_maybe_inject_failure(FailureLocation.force_discharge, self.failure)
        self.battery_mode = BatteryMode.FORCE_DISCHARGE
        self.update_status()

    async def enable_inverter(self) -> None:
        await async_maybe_inject_failure(FailureLocation.enable_inverter, self.failure)
        self.inverter_mode = InverterMode.ENABLE
        self.update_status()

    async def disable_inverter(self, *, change_duration: int) -> None:
        await async_maybe_inject_failure(FailureLocation.disable_inverter, self.failure)
        self.inverter_mode = InverterMode.DISABLE
        self.update_status()

    async def zero_export(self, *, change_duration: int) -> None:
        await async_maybe_inject_failure(FailureLocation.zero_export, self.failure)
        self.inverter_mode = InverterMode.ZERO_EXPORT
        self.update_status()

    def update_status(self) -> None:
        """
        Update simulated power flows and accumulated energy.

        Energy is accumulated using the power values from the preceding update
        and the elapsed time since that update. The current power flows are
        then recalculated from the configured house load and operating modes.
        """
        # accumulate energy
        now_timestamp = now().timestamp()
        hours = (now_timestamp - self.last_accumulation) / 3600
        self.last_accumulation = now_timestamp
        self.accumulated_solar_energy += self.solar_power * hours
        grid_energy = self.grid_power * hours
        batt_energy = self.battery_power * hours
        self.accumulated_grid_energy_import += max(0, grid_energy)
        self.accumulated_grid_energy_export -= min(0, grid_energy)
        self.accumulated_battery_energy_charge += max(0, batt_energy)
        self.accumulated_battery_energy_discharge -= min(0, batt_energy)

        max_generation = self.inverter_limit
        max_charge_param = self.max_charge_param
        max_discharge_param = self.max_discharge_param

        charge_limit = max_charge_param if self.state_of_charge < 100 else 0
        discharge_limit = max_discharge_param if self.state_of_charge > 0 else 0

        match self.inverter_mode:
            case InverterMode.ENABLE:
                self.power_limit = 100
                self.solar_power = max_generation

            case InverterMode.DISABLE:
                self.power_limit = 0
                self.solar_power = 0

            case InverterMode.ZERO_EXPORT:
                # adjusted later
                self.power_limit = 100
                self.solar_power = max_generation

        power_in: float = self.solar_power
        if (
                self.battery_mode == BatteryMode.FORCE_DISCHARGE
                and self.inverter_mode != InverterMode.DISABLE
        ):
            power_in += max(max_discharge_param, discharge_limit)

        power_out: float = self.house_power
        if self.battery_mode == BatteryMode.FORCE_CHARGE:
            power_out += max(max_charge_param, charge_limit)

        excess_power: float = power_in - power_out

        if self.inverter_mode == InverterMode.DISABLE:
            self.battery_power = 0
        else:
            match self.battery_mode:
                case BatteryMode.ENABLE:
                    if excess_power >= 0:
                        self.battery_power = min(excess_power, charge_limit)
                    else:
                        self.battery_power = -min(-excess_power, discharge_limit)
                case BatteryMode.DISABLE:
                    self.battery_power = 0
                case BatteryMode.FORCE_CHARGE:
                    self.battery_power = max(excess_power, max_charge_param)
                case BatteryMode.FORCE_DISCHARGE:
                    self.battery_power = min(excess_power, -max_discharge_param)
                case BatteryMode.CHARGE_ONLY:
                    if excess_power >= 0:
                        self.battery_power = min(excess_power, charge_limit)
                    else:
                        self.battery_power = 0
                case BatteryMode.DISCHARGE_ONLY:
                    if excess_power >= 0:
                        self.battery_power = 0
                    else:
                        self.battery_power = -min(-excess_power, discharge_limit)

        self.grid_power = self.house_power + self.battery_power - self.solar_power

        if self.inverter_mode == InverterMode.ZERO_EXPORT and self.grid_power < 0:
            self.solar_power = max(0, self.solar_power + self.grid_power)
            self.power_limit = self.solar_power / max_generation * 100
            self.grid_power = self.house_power + self.battery_power - self.solar_power

    async def close(self) -> None:
        # nothing to do
        pass
