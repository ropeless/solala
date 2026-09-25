from typing import Iterable, List, Tuple, Sequence

from solala.log import LOGGER
from solala.power_controller.impl_modbus.modbus import Modbus
from solala.power_controller.power_controller import PowerController, PowerStatus


class _DEFAULT:
    """
    Critical registers and their default values.
    """
    MinRsvPct = 7  # Important - minimum reserve battery percentage
    InWRte = 100
    OutWRte = 100
    StorCtl_Mod = 0
    WMaxLimPct = 100
    WMaxLimPct_RvrtTms = 11  # Standard reversion time in seconds


# Prefixes used for logging
_START = '>>>'
_STOP = '<<<'

# Tolerance for 'idle' status.
_STATUS_TOLERANCE = 100  # Watts

# Tolerance for power change.
_POWER_CHANGE_TOLERANCE = 100  # Watts
_SMALL_CHANGE_TOLERANCE = 1000  # Watts


class ModbusPowerController(PowerController):
    """
    High-level power power_controller to send commands and read status from the power system.
    This power power_controller uses Modbus.
    """

    def __init__(
            self,
            modbus: Modbus,
            *,
            master: str = 'master',
            meter: str = 'meter',
            slaves: Iterable[str] = (),
    ):
        """
        Make a power power_controller from a Modbus connection.
        """
        self._modbus: Modbus = modbus
        self._master = master
        self._slaves = list(slaves)
        self._inverters = [self._master] + self._slaves
        self._meter = meter

        # Important registers
        self._ChaState: str = f'{master}/ChaState'
        self._charge_power: str = f'{master}/module/3/DCW'
        self._discharge_power: str = f'{master}/module/4/DCW'
        self._solar_power: List[str] = [f'{inverter}/module/{i}/DCW' for inverter in self._inverters for i in [1, 2]]
        self._grid_power: str = f'{meter}/W'
        self._inverter_power: List[str] = [f'{inverter}/W' for inverter in self._inverters]
        self._WMax: List[str] = [f'{inverter}/WMax' for inverter in self._inverters]
        self._WMaxLim_Ena: str = f'{master}/WMaxLim_Ena'
        self._WMaxLimPct: str = f'{master}/WMaxLimPct'
        self._WMaxLimPct_RvrtTms: str = f'{master}/WMaxLimPct_RvrtTms'
        self._InWRte: str = f'{master}/InWRte'
        self._OutWRte: str = f'{master}/OutWRte'
        self._StorCtl_Mod: str = f'{master}/StorCtl_Mod'
        self._MinRsvPct: str = f'{master}/MinRsvPct'

        # Log all registers and their values
        for register, value in self.get_registers():
            LOGGER.info(f'LOG {register}: {value!r}')

    def connect(self) -> None:
        """
        Delegate `connect` to Modbus clients.
        """
        self._modbus.connect()

    def close(self) -> None:
        """
        Delegate `close` to Modbus clients.
        """
        self._modbus.close()

    def get_registers(self) -> Iterable[Tuple[str, int | float | str]]:
        """
        Get the values of all known registers.
        """
        return self._modbus.items()

    def get_status(self) -> PowerStatus:
        """
        Get a high-level status of the system.
        """
        LOGGER.info(f'{_START} get_status')
        state_of_charge = self._get(self._ChaState)
        charge_power = self._get(self._charge_power)
        discharge_power = self._get(self._discharge_power)
        solar_power = self._get_sum(self._solar_power)
        grid_power = self._get(self._grid_power)

        battery_power = charge_power - discharge_power
        house_power = grid_power + solar_power - battery_power

        battery_status = _status(battery_power, 'discharging', 'charging')
        grid_status = _status(grid_power, 'exporting', 'importing')
        power_limit_enabled: bool = (self._get(self._WMaxLim_Ena) != 0)
        power_limit: float = self._get(self._WMaxLimPct) if power_limit_enabled else 100.0

        LOGGER.info(f'{_STOP} get_status')

        return PowerStatus(
            state_of_charge=state_of_charge,
            battery_status=battery_status,
            grid_status=grid_status,
            power_limit=power_limit,
            grid_power=grid_power,
            solar_power=solar_power,
            battery_power=battery_power,
            house_power=house_power,
        )

    # =================================================
    #  Battery Control
    # =================================================

    def enable_battery(self) -> None:
        """
        Allow the battery to charge and discharge.
        This is the normal state.
        """
        LOGGER.info(f'{_START} enable_battery')
        self._set(self._InWRte, _DEFAULT.InWRte)
        self._set(self._OutWRte, _DEFAULT.OutWRte)
        self._set(self._StorCtl_Mod, _DEFAULT.StorCtl_Mod)
        self._set(self._MinRsvPct, _DEFAULT.MinRsvPct)
        LOGGER.info(f'{_STOP} enable_battery')

    def disable_battery(self) -> None:
        """
        Stop the battery from charging and discharging.
        """
        LOGGER.info(f'{_START} disable_battery')
        self._set(self._InWRte, 0)
        self._set(self._OutWRte, 0)
        self._set(self._StorCtl_Mod, 3)
        self._set(self._MinRsvPct, _DEFAULT.MinRsvPct)
        LOGGER.info(f'{_STOP} disable_battery')

    def force_charge(self) -> None:
        """
        Force the battery to charge.
        This will aim to charge the battery to its maximum capacity,
        even if it means drawing from the grid.
        """
        LOGGER.info(f'{_START} force_charge')
        self._set(self._InWRte, _DEFAULT.InWRte)
        self._set(self._OutWRte, _DEFAULT.OutWRte)
        self._set(self._StorCtl_Mod, 3)
        self._set(self._MinRsvPct, 100)
        LOGGER.info(f'{_STOP} force_charge')

    def force_discharge(self) -> None:
        """
        Force the battery to discharge.
        This is a way to force stored power to the grid.
        """
        LOGGER.info(f'{_START} force_discharge')
        self._set(self._InWRte, -_DEFAULT.InWRte)  # negative flow
        self._set(self._OutWRte, _DEFAULT.OutWRte)
        self._set(self._StorCtl_Mod, 3)
        self._set(self._MinRsvPct, _DEFAULT.MinRsvPct)
        LOGGER.info(f'{_STOP} force_discharge')

    # =================================================
    #  Grid Export Control
    # =================================================

    def enable_inverter(self) -> None:
        LOGGER.info(f'{_START} enable_inverter')
        self._set_power_pct(_DEFAULT.WMaxLimPct)
        LOGGER.info(f'{_STOP} enable_inverter')

    def disable_inverter(self, *, change_duration: int) -> None:
        LOGGER.info(f'{_START} disable_inverter')
        self._set_power_pct(0, change_duration)
        LOGGER.info(f'{_STOP} disable_inverter')

    def zero_export(self, *, change_duration: int) -> None:
        """
        Limit inverter output power to balance consumption, so there is no export.
        Will still allow drawing from the grid if insufficient solar supply for demand.
        This may need to be repeatedly called as the consumption may change,
        or the change duration expires.
        """
        LOGGER.info(f'{_START} zero_export')

        cur_grid_power: float = self._get(self._grid_power)
        cur_pct: float = self._get(self._WMaxLimPct[0])  # just get the master
        max_power: float = self._get_sum(self._WMax)
        cur_power: float = self._get_sum(self._inverter_power)

        abs_grid_power = abs(cur_grid_power)
        max_power = max(max_power, cur_power)  # incase the inverter is oversupplying - simplifies maths

        if abs_grid_power < _POWER_CHANGE_TOLERANCE:
            # Not worth changing power settings
            LOGGER.info(f'using existing limit {cur_pct:.2f}, export too small')

            new_pct = cur_pct
            new_power = cur_power
        elif abs_grid_power < _SMALL_CHANGE_TOLERANCE:
            # Small power change - use the hunting method
            LOGGER.info('using hunting method')

            if cur_grid_power < 0:
                # Exporting - reduce power
                new_pct = cur_pct - cur_pct * (cur_power / max_power)
            elif cur_grid_power > 0:
                # Importing - increase power
                new_pct = cur_pct + (100 - cur_pct) * (cur_power / max_power)
            else:
                new_pct = cur_pct
            new_pct = round(max(0, min(new_pct, 100)), 2)
            new_power = cur_power + cur_grid_power * (cur_pct - new_pct) / 100
            new_power = max(0, min(new_power, max_power))

        else:
            # Small power change - use the exact method
            LOGGER.info('using exact method')

            new_power = cur_power + cur_grid_power
            new_power = max(0, min(new_power, max_power))

            new_pct = new_power / max_power * 100
            new_pct = round(max(0, min(new_pct, 100)), 2)

        power_change = new_power - cur_power
        LOGGER.info(f'max power: {max_power:.2f}')
        LOGGER.info(f'power change: {cur_power:.2f} -> {new_power:.2f} ({power_change:.2f})')
        LOGGER.info(f'grid change: {cur_grid_power:.2f} -> {cur_grid_power - power_change:.2f} ({power_change:.2f})')
        LOGGER.info(f'percent change: {cur_pct:.2f} -> {new_pct:.2f}')

        self._set_power_pct(new_pct, change_duration)
        LOGGER.info(f'{_STOP} zero_export')

    # =================================================
    #  Support
    # =================================================

    def _set_power_pct(self, pct: float, change_duration: int = _DEFAULT.WMaxLimPct_RvrtTms) -> None:
        if pct >= 100:
            self._set(self._WMaxLimPct, _DEFAULT.WMaxLimPct)
            self._set(self._WMaxLimPct_RvrtTms, change_duration)
            self._set(self._WMaxLim_Ena, 0)
        else:
            self._set(self._WMaxLimPct, pct)
            self._set(self._WMaxLimPct_RvrtTms, change_duration)
            self._set(self._WMaxLim_Ena, 1, force=True)  # force to keep alive

    def _set(self, name: str, value: int | float, *, force: bool = False) -> None:
        """
        Set the value of the named register, logging its old and new value, and
        verifying the change.
        """
        old = self._modbus[name]
        if not force and old == value:
            # No change needed
            LOGGER.info(f'SET {name}: {old!r} -> {value!r} UNCHANGED')
        else:
            # Make the change
            self._modbus[name] = value
            new = self._modbus[name]
            msg = 'FAILED' if abs(new - value) > 10e-6 else 'OK'
            LOGGER.info(f'SET {name}: {old!r} -> {value!r} checked {new!r} {msg}')

    def _set_all(self, names: Iterable[str], value: int | float, *, force: bool = False) -> None:
        """
        Set the value of all the named registers to the given value.
        """
        for name in names:
            self._set(name, value, force=force)

    def _get(self, name: str) -> int | float:
        """
        Get the value of the named register, logging its value, and
        ensuring it is an int or float.
        """
        value = self._modbus[name]
        LOGGER.info(f'GET {name}: {value!r}')
        if not isinstance(value, (int, float)):
            msg = f'getting register {name!r}: Expected int or float, got {type(value)}'
            LOGGER.error(msg)
            raise TypeError(msg)
        return value

    def _get_sum(self, names: Sequence[str]) -> int | float:
        LOGGER.info(f'SUM {names}')
        result = sum(self._get(name) for name in names)
        LOGGER.info(f'SUM = {result}')
        return result

    def _get_sum_abs(self, names: Sequence[str]) -> int | float:
        LOGGER.info(f'SUM-ABS {names}')
        result = sum(abs(self._get(name)) for name in names)
        LOGGER.info(f'SUM-ABS = {result}')
        return result


def _status(power: float, negative_status: str, positive_status: str, idle_status: str = 'idle') -> str:
    """
    Select a 'status' string, depending on the value of 'power'.
    Status is considered 'idle' if `- _STATUS_TOLERANCE <= power <= _STATUS_TOLERANCE`.

    Args:
        power: value to test
        negative_status: string to return if power is negative
        positive_status: string to return if power is positive
        idle_status: string to return if power is zero

    Returns:
        the selected status string.
    """
    if power > _STATUS_TOLERANCE:
        return positive_status
    elif power < -_STATUS_TOLERANCE:
        return negative_status
    else:
        return idle_status
