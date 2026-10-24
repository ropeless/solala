from contextlib import contextmanager
from typing import Iterable, List, Tuple, Sequence, Optional, Dict

from solala.logger import LOGGER
from solala.power_controller.modbus_power_controller.modbus import Modbus, ModbusDevice
from solala.power_controller.modbus_power_controller.register_access import ModbusError
from solala.power_controller.power_controller import PowerController, PowerStatus
from solala.utils.json import JSONDict


class _DEFAULT:
    """
    Critical registers and their default values.
    """
    MinRsvPct = 7  # Minimum reserve battery percentage
    WMaxLimPct_RvrtTms = 11  # Control reversion time in seconds


# Prefixes used for logging
_START = '>>>'
_STOP = '<<<'

# Tolerance for 'idle' status.
_STATUS_TOLERANCE = 100  # Watts

# Tolerance for power change.
_POWER_CHANGE_TOLERANCE = 100  # Watts
_SMALL_CHANGE_TOLERANCE = 2000  # Watts


class ModbusPowerController(PowerController):
    """
    High-level power controller to send commands and read status from the power system.
    This power controller uses Modbus.
    """

    def __init__(
            self,
            modbus: Modbus,
            *,
            master: str = 'master',
            meter: str = 'meter',
            slaves: Iterable[str] = (),
            mac_addr_lookup: Optional[Dict[str, str]] = None,
    ):
        """
        Make a power controller from a Modbus connection.
        """
        self._modbus: Modbus = modbus
        self._master = master
        self._slaves = list(slaves)
        self._inverters = [self._master] + self._slaves
        self._meter = meter
        self._log_set_get: bool = False

        # Important registers
        self._ChaState: str = f'{master}/ChaState'
        self._charge_power: str = f'{master}/module/3/DCW'
        self._discharge_power: str = f'{master}/module/4/DCW'
        self._solar_power: List[str] = [f'{inverter}/module/{i}/DCW' for inverter in self._inverters for i in [1, 2]]
        self._grid_power: str = f'{meter}/W'
        self._inverter_power: List[str] = [f'{inverter}/W' for inverter in self._inverters]
        self._WMaxLim_Ena: str = f'{master}/WMaxLim_Ena'
        self._WMaxLimPct: str = f'{master}/WMaxLimPct'
        self._WMaxLimPct_RvrtTms: str = f'{master}/WMaxLimPct_RvrtTms'
        self._InWRte: str = f'{master}/InWRte'
        self._OutWRte: str = f'{master}/OutWRte'
        self._StorCtl_Mod: str = f'{master}/StorCtl_Mod'
        self._MinRsvPct: str = f'{master}/MinRsvPct'
        self._ChaGriSet: str = f'{master}/ChaGriSet'

        # Save the connection status
        devices_record: JSONDict = {}
        unnamed_device: Optional[JSONDict] = None
        device_name: Optional[str]
        device: ModbusDevice
        for device_name, device in modbus.devices().items():
            host: str = device.client.comm_params.host
            device_record: JSONDict = {'host': host}
            if mac_addr_lookup is not None:
                mac_address: Optional[str] = mac_addr_lookup.get(host)
                if mac_address is not None and mac_address != '':
                    device_record['mac_address'] = mac_address
            device_record['device'] = device.device_id
            if device_name is None:
                unnamed_device = device_record
            else:
                devices_record[device_name] = device_record
        self._connection_status = {
            'connection': 'Modbus',
            'devices': devices_record,
        }
        if unnamed_device is not None:
            self._connection_status['unnamed_device'] = unnamed_device

        # Log all registers and their values
        for register, value in self.get_registers():
            LOGGER.info(f'LOG {register}: {value!r}')

        # Calculate the constant inverter limit
        value: float = 0
        for inverter in self._inverters:
            w_max = self._get(f'{inverter}/WMax')
            w_rtg = self._get(f'{inverter}/WRtg')
            value += min(w_max, w_rtg)
        self._inverter_limit = value
        LOGGER.info(f'LOG inverter_limit: {value!r}')

    def connect(self) -> None:
        """
        Delegate `connect` to Modbus clients.
        """
        self._modbus.connect()

    def get_inverter_limit(self) -> float:
        return self._inverter_limit

    def get_connection_status(self) -> JSONDict:
        return self._connection_status

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
        state_of_charge = self._get(self._ChaState)
        charge_power = self._get(self._charge_power)
        discharge_power = self._get(self._discharge_power)
        solar_power = self._get_sum(self._solar_power)
        grid_power = self._get(self._grid_power)

        battery_power = charge_power - discharge_power
        house_power = grid_power + solar_power - battery_power

        power_limit_enabled: bool = (self._get(self._WMaxLim_Ena) != 0)
        power_limit: float = self._get(self._WMaxLimPct) if power_limit_enabled else 100.0

        return PowerStatus(
            state_of_charge=state_of_charge,
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
        with self._logit('enable_battery'):
            self._set(self._StorCtl_Mod, 0)
            self._set(self._InWRte, 100)
            self._set(self._OutWRte, 100)
            self._set(self._ChaGriSet, 0)
            self._set(self._MinRsvPct, _DEFAULT.MinRsvPct)

    def disable_battery(self) -> None:
        """
        Stop the battery from charging and discharging.
        """
        with self._logit('disable_battery'):
            self._set(self._StorCtl_Mod, 0)  # Temp to avoid any invalid value exception
            self._set(self._InWRte, 0)
            self._set(self._OutWRte, 0)
            self._set(self._StorCtl_Mod, 3)
            self._set(self._ChaGriSet, 0)
            self._set(self._MinRsvPct, _DEFAULT.MinRsvPct)

    def force_charge(self) -> None:
        """
        Force the battery to charge.
        This will aim to charge the battery to its maximum capacity,
        even if it means drawing from the grid.
        """
        with self._logit('force_charge'):
            self._set(self._StorCtl_Mod, 0)  # Temp to avoid any invalid value exception
            self._set(self._InWRte, 100)
            self._set(self._OutWRte, 0)  # Don't try to discharge at the same time as charging
            self._set(self._StorCtl_Mod, 3)
            self._set(self._ChaGriSet, 1)
            self._set(self._MinRsvPct, 100)

    def force_discharge(self) -> None:
        """
        Force the battery to discharge.
        This is a way to force stored power to the grid.
        """
        with self._logit('force_discharge'):
            self._set(self._StorCtl_Mod, 0)  # Temp to avoid any invalid value exception
            self._set(self._InWRte, -100)  # negative flow
            self._set(self._OutWRte, 100)
            self._set(self._StorCtl_Mod, 3)
            self._set(self._ChaGriSet, 0)
            self._set(self._MinRsvPct, _DEFAULT.MinRsvPct)

    def charge_only(self) -> None:
        """
        Allow charging but not discharging.
        """
        with self._logit('charge_only'):
            self._set(self._StorCtl_Mod, 0)  # Temp to avoid any invalid value exception
            self._set(self._InWRte, 100)
            self._set(self._OutWRte, 0)
            self._set(self._StorCtl_Mod, 3)
            self._set(self._ChaGriSet, 0)
            self._set(self._MinRsvPct, _DEFAULT.MinRsvPct)

    def discharge_only(self) -> None:
        """
        Allow discharging but not charging.
        """
        with self._logit('discharge_only'):
            self._set(self._StorCtl_Mod, 0)  # Temp to avoid any invalid value exception
            self._set(self._InWRte, 0)
            self._set(self._OutWRte, 100)
            self._set(self._StorCtl_Mod, 3)
            self._set(self._ChaGriSet, 0)
            self._set(self._MinRsvPct, _DEFAULT.MinRsvPct)

    # =================================================
    #  Grid Export Control
    # =================================================

    def enable_inverter(self) -> None:
        with self._logit('enable_inverter'):
            self._set_power_pct(100)

    def disable_inverter(self, *, change_duration: int) -> None:
        with self._logit('disable_inverter'):
            self._set_power_pct(0, change_duration)

    def zero_export(self, *, change_duration: int) -> None:
        """
        Limit inverter output power to balance consumption, so there is no export.
        Will still allow drawing from the grid if insufficient solar supply for demand.
        This may need to be repeatedly called as the consumption may change,
        or the change duration expires.
        """
        with self._logit('zero_export'):
            grid_power: float = self._get(self._grid_power)
            cur_pct: float = self._get(self._WMaxLimPct)
            max_power: float = self.get_inverter_limit()
            cur_power: float = self._get_sum(self._inverter_power)

            abs_grid_power = abs(grid_power)
            max_power = max(max_power, cur_power)  # incase the inverter is oversupplying - simplifies maths

            if abs_grid_power < _POWER_CHANGE_TOLERANCE:
                # Not worth changing power settings
                LOGGER.info(f'using existing limit {cur_pct:.2f}, export too small')

                new_pct = cur_pct
                new_power = cur_power
            elif abs_grid_power < _SMALL_CHANGE_TOLERANCE:
                # Small power change - use the hunting method
                LOGGER.info('using hunting method')

                if grid_power < 0:
                    # Exporting - reduce power
                    new_pct = cur_pct - cur_pct * (cur_power / max_power)
                elif grid_power > 0:
                    # Importing - increase power
                    new_pct = cur_pct + (100 - cur_pct) * (cur_power / max_power)
                else:
                    new_pct = cur_pct
                new_pct = round(max(0, min(new_pct, 100)), 2)
                new_power = cur_power + grid_power * (cur_pct - new_pct) / 100
                new_power = max(0, min(new_power, max_power))

            else:
                # Small power change - use the exact method
                LOGGER.info('using exact method')

                new_power = cur_power + grid_power
                new_power = max(0, min(new_power, max_power))

                new_pct = new_power / max_power * 100
                new_pct = round(max(0, min(new_pct, 100)), 2)

            power_change = new_power - cur_power
            LOGGER.info(f'max power: {max_power:.2f}')
            LOGGER.info(f'power change: {cur_power:.2f} -> {new_power:.2f} ({power_change:.2f})')
            LOGGER.info(f'grid change: {grid_power:.2f} -> {grid_power - power_change:.2f} ({power_change:.2f})')
            LOGGER.info(f'percent change: {cur_pct:.2f} -> {new_pct:.2f}')

            self._set_power_pct(new_pct, change_duration)

    # =================================================
    #  Support
    # =================================================

    @contextmanager
    def _logit(self, name: str):
        self._log_set_get = True
        LOGGER.info(f'{_START} {name}')
        yield
        LOGGER.info(f'{_STOP} {name}')
        self._log_set_get = False

    def _logger_get_set(self, message: str) -> None:
        if self._log_set_get:
            LOGGER.info(message)

    def _set_power_pct(self, pct: float, change_duration: int = _DEFAULT.WMaxLimPct_RvrtTms) -> None:
        if pct >= 100:
            self._set(self._WMaxLimPct, 100)
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
            self._logger_get_set(f'SET {name}: {old!r} -> {value!r} UNCHANGED')
        else:
            # Make the change
            try:
                self._modbus[name] = value
            except ModbusError as err:
                LOGGER.error(f'SET {name}: {old!r} -> {value!r} ERROR: {err}')
                LOGGER.error(f'Modbus message: {err.modbus_message!r}')
                return

            new = self._modbus[name]
            failed: bool = abs(new - value) > 10e-6
            if failed:
                LOGGER.error(f'SET {name}: {old!r} -> {value!r} checked {new!r} FAILED')
            elif force:
                self._logger_get_set(f'SET {name}: {old!r} -> {value!r} checked {new!r} OK FORCED')
            else:
                self._logger_get_set(f'SET {name}: {old!r} -> {value!r} checked {new!r} OK')

    def _get(self, name: str) -> int | float:
        """
        Get the value of the named register, logging its value, and
        ensuring it is an int or float.
        """
        value = self._modbus[name]
        self._logger_get_set(f'GET {name}: {value!r}')
        if not isinstance(value, (int, float)):
            msg = f'getting register {name!r}: Expected int or float, got {type(value)}'
            LOGGER.error(msg)
            raise TypeError(msg)
        return value

    def _get_sum(self, names: Sequence[str]) -> int | float:
        self._logger_get_set(f'SUM {names}')
        result = sum(self._get(name) for name in names)
        self._logger_get_set(f'SUM = {result}')
        return result
