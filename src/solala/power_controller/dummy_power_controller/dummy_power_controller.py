from typing import Iterable, Tuple

from solala.power_controller.power_controller import PowerController, PowerStatus


class DummyPowerController(PowerController):
    """
    A dummy power controller for testing and demonstration purposes.

    This power controller approximately simulates a simple power system.
    """

    def __init__(self) -> None:
        self.state_of_charge = 50

        self.power_limit = 0
        self.house_power = 0
        self.battery_power = 0
        self.grid_power = 0
        self.solar_power = 0
        self.battery_mode = ''
        self.inverter_mode = ''

        self.enable_battery()
        self.enable_inverter()

    def get_registers(self) -> Iterable[Tuple[str, int | float | str]]:
        return (
            ('controller', 'dummy'),
            ('battery_mode', self.battery_mode),
            ('inverter_mode', self.inverter_mode),
            ('state_of_charge', self.state_of_charge),
            ('power_limit', self.power_limit),
            ('battery_power', self.battery_power),
            ('grid_power', self.grid_power),
            ('solar_power', self.solar_power),
            ('house_power', self.house_power),
        )

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
        self.house_power = 3000

        generation_param = 5000
        force_charge_param = 3000
        force_discharge_param = 3000

        charge_limit = 5000 if self.state_of_charge < 100 else 0
        discharge_limit = 5000 if self.state_of_charge > 0 else 0

        match self.inverter_mode:
            case 'enable':
                self.power_limit = 100
                self.solar_power = generation_param

            case 'disable':
                self.power_limit = 0
                self.solar_power = 0

            case 'zero_export':
                # adjusted later
                self.power_limit = 100
                self.solar_power = generation_param

        power_in: float = self.solar_power
        if self.battery_mode == 'force_discharge' and self.inverter_mode != 'disable':
            power_in += max(force_discharge_param, discharge_limit)

        power_out: float = self.house_power
        if self.battery_mode == 'force_charge':
            power_out += max(force_charge_param, charge_limit)

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
                    self.battery_power = max(excess_power, force_charge_param)
                case 'force_discharge':
                    self.battery_power = min(excess_power, -force_discharge_param)

        self.grid_power = self.house_power + self.battery_power - self.solar_power

        if self.inverter_mode == 'zero_export' and self.grid_power < 0:
            self.solar_power = max(0, self.solar_power + self.grid_power)
            self.power_limit = self.solar_power / generation_param * 100
            self.grid_power = self.house_power + self.battery_power - self.solar_power

    def close(self) -> None:
        # nothing to do
        pass
