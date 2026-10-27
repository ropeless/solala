from enum import Enum, auto
from typing import Iterable, Tuple, Dict

from solala.delegates.power_controller.power_controller import PowerController, PowerStatus


class BatteryMode(Enum):
    ENABLE = auto()
    DISABLE = auto()
    FORCE_CHARGE = auto()
    FORCE_DISCHARGE = auto()
    CHARGE_ONLY = auto()
    DISCHARGE_ONLY = auto()


class InverterMode(Enum):
    ENABLE = auto()
    DISABLE = auto()
    ZERO_EXPORT = auto()


class DummyPowerController(PowerController):
    """
    A dummy power controller for testing and demonstration purposes.

    This power controller approximately simulates a simple power system.
    """

    def __init__(
            self,
            *,
            inverter_limit: float,
            house_power: float,
            max_charge_param: float,
            max_discharge_param: float,

    ) -> None:
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

        self.update_status()

    def get_inverter_limit(self) -> float:
        return self.inverter_limit

    def get_connection_status(self) -> Dict[str, int | float | str]:
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

    async def get_registers(self) -> Iterable[Tuple[str, int | float | str]]:
        return self.get_connection_status().items()

    async def get_status(self) -> PowerStatus:
        return PowerStatus(
            state_of_charge=self.state_of_charge,
            power_limit=self.power_limit,
            battery_power=self.battery_power,
            grid_power=self.grid_power,
            solar_power=self.solar_power,
            house_power=self.house_power,
        )

    def enable_battery(self) -> None:
        self.battery_mode = BatteryMode.ENABLE
        self.update_status()

    def disable_battery(self) -> None:
        self.battery_mode = BatteryMode.DISABLE
        self.update_status()

    def charge_only(self) -> None:
        self.battery_mode = BatteryMode.CHARGE_ONLY
        self.update_status()

    def discharge_only(self) -> None:
        self.battery_mode = BatteryMode.DISCHARGE_ONLY
        self.update_status()

    def force_charge(self) -> None:
        self.battery_mode = BatteryMode.FORCE_CHARGE
        self.update_status()

    def force_discharge(self) -> None:
        self.battery_mode = BatteryMode.FORCE_DISCHARGE
        self.update_status()

    def enable_inverter(self) -> None:
        self.inverter_mode = InverterMode.ENABLE
        self.update_status()

    def disable_inverter(self, *, change_duration: int) -> None:
        self.inverter_mode = InverterMode.DISABLE
        self.update_status()

    def zero_export(self, *, change_duration: int) -> None:
        self.inverter_mode = InverterMode.ZERO_EXPORT
        self.update_status()

    def update_status(self) -> None:
        """
        Simulate a simple power system.
        """
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
