from dataclasses import dataclass, asdict

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
