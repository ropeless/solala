from typing import Iterable, Tuple, Dict

from solala.power_controller.power_controller import PowerController, PowerStatus


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
        self.battery_mode = ''
        self.inverter_mode = ''

        self.inverter_limit = inverter_limit
        self.max_charge_param = max_charge_param
        self.max_discharge_param = max_discharge_param

        self.enable_battery()
        self.enable_inverter()

    def get_inverter_limit(self) -> float:
        return self.inverter_limit

    def get_connection_status(self) -> Dict[str, int | float | str]:
        return {
            'connection': self.__class__.__name__,
            'battery_mode': self.battery_mode,
            'inverter_mode': self.inverter_mode,
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

    def get_registers(self) -> Iterable[Tuple[str, int | float | str]]:
        return self.get_connection_status().items()

    def get_status(self) -> PowerStatus:
        return PowerStatus(
            state_of_charge=self.state_of_charge,
            power_limit=self.power_limit,
            battery_power=self.battery_power,
            grid_power=self.grid_power,
            solar_power=self.solar_power,
            house_power=self.house_power,
        )

    def enable_battery(self) -> None:
        self.battery_mode = 'enable'
        self.update_status()

    def disable_battery(self) -> None:
        self.battery_mode = 'disable'
        self.update_status()

    def force_charge(self) -> None:
        self.battery_mode = 'force_charge'
        self.update_status()

    def force_discharge(self) -> None:
        self.battery_mode = 'force_discharge'
        self.update_status()

    def enable_inverter(self) -> None:
        self.inverter_mode = 'enable'
        self.update_status()

    def disable_inverter(self, *, change_duration: int) -> None:
        self.inverter_mode = 'disable'
        self.update_status()

    def zero_export(self, *, change_duration: int) -> None:
        self.inverter_mode = 'zero_export'
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
            case 'enable':
                self.power_limit = 100
                self.solar_power = max_generation

            case 'disable':
                self.power_limit = 0
                self.solar_power = 0

            case 'zero_export':
                # adjusted later
                self.power_limit = 100
                self.solar_power = max_generation

        power_in: float = self.solar_power
        if self.battery_mode == 'force_discharge' and self.inverter_mode != 'disable':
            power_in += max(max_discharge_param, discharge_limit)

        power_out: float = self.house_power
        if self.battery_mode == 'force_charge':
            power_out += max(max_charge_param, charge_limit)

        excess_power: float = power_in - power_out

        if self.inverter_mode == 'disable':
            self.battery_power = 0
        else:
            match self.battery_mode:
                case 'enable':
                    if excess_power >= 0:
                        self.battery_power = min(excess_power, charge_limit)
                    else:
                        self.battery_power = -min(-excess_power, discharge_limit)
                case 'disable':
                    self.battery_power = 0
                case 'force_charge':
                    self.battery_power = max(excess_power, max_charge_param)
                case 'force_discharge':
                    self.battery_power = min(excess_power, -max_discharge_param)

        self.grid_power = self.house_power + self.battery_power - self.solar_power

        if self.inverter_mode == 'zero_export' and self.grid_power < 0:
            self.solar_power = max(0, self.solar_power + self.grid_power)
            self.power_limit = self.solar_power / max_generation * 100
            self.grid_power = self.house_power + self.battery_power - self.solar_power

    def close(self) -> None:
        # nothing to do
        pass
