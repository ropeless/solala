from contextlib import contextmanager
from typing import Iterable, List, Optional, Dict, Tuple

from solala.delegates.power_controller.modbus_power_controller.modbus import Modbus, ModbusDevice
from solala.delegates.power_controller.modbus_power_controller.modbus_register_access import ModbusError
from solala.delegates.power_controller.power_controller import PowerController, PowerStatus
from solala.logger import LOGGER
from solala.registers import RegisterBank, Register, ConstantRegister, RegisterValue
from solala.utils.json_extras import JSONDict, JSONValue


class _DEFAULT:
    """
    Critical registers and their default values.
    """
    MinRsvPct = 7  # Minimum reserve battery percentage
    WMaxLimPct_RvrtTms = 11  # Control reversion time in seconds


# Prefixes used for logging
_START = '>>>'
_STOP = '<<<'

# Tolerance for power change.
_POWER_CHANGE_TOLERANCE = 100  # Watts
_SMALL_CHANGE_TOLERANCE = 2000  # Watts  Grid power threshold to change to "hunting" method
_GAMMA = 0.1  # Hunting method parameter

_INVERTER_LIMIT_NAME: str = 'inverter_limit'


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
            power_control_slaves: bool = False,
    ):
        """
        Make a power controller from a Modbus connection.

        Args:
            modbus: Modbus connections.
            master: the name of the master inverter device in `modbus`.
            slaves: the names of any slave inverter devices in `modbus`.
            meter: the name of the grid meter device in `modbus`.
            mac_addr_lookup: optional mac addresses for recording in the connection status.
            power_control_slaves: shoul;d power limit controls be sent to the slaves or not; if not then
                power control is sent only to the master.
        """
        self._modbus: Modbus = modbus
        self._master = master
        self._slaves = list(slaves)
        self._inverters = [self._master] + self._slaves
        self._meter = meter
        self._log_set_get: bool = False
        self._hunt_history: List[float] = []
        self._is_force_discharge: bool = False

        # Important registers
        self._ChaState: str = f'{master}/ChaState'
        self._charge_power: str = f'{master}/module/3/DCW'
        self._discharge_power: str = f'{master}/module/4/DCW'
        self._solar_power: List[str] = [f'{inverter}/module/{i}/DCW' for inverter in self._inverters for i in [1, 2]]
        self._grid_power: str = f'{meter}/W'
        self._inverter_power: List[str] = [f'{inverter}/W' for inverter in self._inverters]

        self._accumulated_grid_import: str = f'{meter}/TotWhImp'
        self._accumulated_grid_export: str = f'{meter}/TotWhExp'
        self._accumulated_solar_energy: List[str] = [f'{inverter}/module/{i}/DCWH' for inverter in self._inverters for i
                                                     in [1, 2]]
        self._accumulated_charge_energy: str = f'{master}/module/3/DCWH'
        self._accumulated_discharge_energy: str = f'{master}/module/4/DCWH'
        # self._accumulated_inverter_power: List[str] = [f'{inverter}/ActWh' for inverter in self._inverters]

        if power_control_slaves:
            self._power_controllers: List[str] = self._inverters
        else:
            self._power_controllers: List[str] = [master]
        self._WMaxLim_Ena: List[str] = [f'{inverter}/WMaxLim_Ena' for inverter in self._power_controllers]
        self._WMaxLimPct: List[str] = [f'{inverter}/WMaxLimPct' for inverter in self._power_controllers]
        self._WMaxLimPct_RvrtTms: List[str] = [f'{inverter}/WMaxLimPct_RvrtTms' for inverter in self._power_controllers]

        self._InWRte: str = f'{master}/InWRte'
        self._OutWRte: str = f'{master}/OutWRte'
        self._StorCtl_Mod: str = f'{master}/StorCtl_Mod'
        self._MinRsvPct: str = f'{master}/MinRsvPct'
        self._ChaGriSet: str = f'{master}/ChaGriSet'

        # Save the connection status
        devices_record: Dict[str, JSONValue] = {}
        unnamed_device: Optional[JSONDict] = None
        device_name: Optional[str]
        device: ModbusDevice
        for device_name, device in modbus.devices().items():
            host: str = device.client.comm_params.host
            device_record: Dict[str, JSONValue] = {'host': host}
            if mac_addr_lookup is not None:
                mac_address: Optional[str] = mac_addr_lookup.get(host)
                if mac_address is not None and mac_address != '':
                    device_record['mac_address'] = mac_address
            device_record['device'] = device.device_id
            if device_name is None:
                unnamed_device = device_record
            else:
                devices_record[device_name] = device_record
        self._connection_status: Dict[str, JSONValue] = {
            'connection': 'Modbus',
            'devices': devices_record,
        }
        if unnamed_device is not None:
            self._connection_status['unnamed_device'] = unnamed_device

        # Calculate the constant inverter limit
        self._inverters_limit: List[float] = []
        total_limit: float = 0.0
        for inverter in self._inverters:
            w_max = self._get(f'{inverter}/WMax')
            w_rtg = self._get(f'{inverter}/WRtg')
            limit = min(w_max, w_rtg)
            self._inverters_limit.append(limit)
            total_limit += limit
        self._inverter_limit: float = total_limit
        self._inverters_limit_proportion: List[float] = [
            limit / self._inverter_limit
            for limit in self._inverters_limit
        ]

        registers: Dict[str, Register] = dict(self._modbus.registers)
        registers[_INVERTER_LIMIT_NAME] = ConstantRegister(self._inverter_limit)
        self._registers: RegisterBank = RegisterBank(registers)

        # Log all registers and their values
        register: str
        value: RegisterValue
        for register, value in self._registers.items():
            LOGGER.info(f'LOG {register}: {value!r}')

    def connect(self) -> None:
        """
        Delegate `connect` to Modbus clients.
        """
        self._modbus.connect()

    def get_inverter_limit(self) -> float:
        return self._inverter_limit

    def get_connection_status(self) -> JSONDict:
        return self._connection_status

    async def close(self) -> None:
        """
        Delegate `close` to Modbus clients.
        """
        self._modbus.close()

    async def get_registers(self) -> RegisterBank:
        """
        Get the values of all known registers.
        """
        return self._registers

    async def get_status(self) -> PowerStatus:
        """
        Get a high-level status of the system.
        """
        state_of_charge = self._get(self._ChaState)
        charge_power = self._get(self._charge_power)
        discharge_power = self._get(self._discharge_power)
        solar_power = self._get_sum(self._solar_power)
        grid_power = self._get(self._grid_power)

        accumulated_grid_import = self._get(self._accumulated_grid_import)
        accumulated_grid_export = self._get(self._accumulated_grid_export)
        accumulated_solar_energy = self._get_sum(self._accumulated_solar_energy)
        accumulated_charge_energy = self._get(self._accumulated_charge_energy)
        accumulated_discharge_energy = self._get(self._accumulated_discharge_energy)
        # accumulated_inverter_power = self._get_sum(self._accumulated_inverter_power)

        battery_power = charge_power - discharge_power
        house_power = grid_power + solar_power - battery_power

        power_limit, power_limit_enabled = self._get_power_limit()

        return PowerStatus(
            state_of_charge=state_of_charge,
            power_limit=power_limit,
            grid_power=grid_power,
            solar_power=solar_power,
            battery_power=battery_power,
            house_power=house_power,
            accumulated_solar_energy=accumulated_solar_energy,
            accumulated_grid_energy_import=accumulated_grid_import,
            accumulated_grid_energy_export=accumulated_grid_export,
            accumulated_battery_energy_charge=accumulated_charge_energy,
            accumulated_battery_energy_discharge=accumulated_discharge_energy,
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
            self._is_force_discharge = False

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
            self._is_force_discharge = False

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
            self._is_force_discharge = False

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
            self._is_force_discharge = True

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
            self._is_force_discharge = False

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
            self._is_force_discharge = False

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
            cur_pct: float
            cur_pct, _ = self._get_power_limit()
            grid_power: float = self._get(self._grid_power)
            max_power: float = self.get_inverter_limit()
            cur_power: float = self._get_sum(self._inverter_power)

            # If the battery is discharging and it not a forced discharge then
            # We actually need that power as well.
            if not self._is_force_discharge:
                discharge_power = self._get(self._discharge_power)
                cur_power += discharge_power

            abs_grid_power = abs(grid_power)
            max_power = max(max_power, cur_power)  # incase the inverter is oversupplying - simplifies maths

            if abs_grid_power < _POWER_CHANGE_TOLERANCE:
                # Not worth changing power settings
                LOGGER.info(f'using existing limit {cur_pct:.2f}, export too small')

                new_pct = cur_pct
                new_power = cur_power
                self._hunt_history = []

            elif abs_grid_power < _SMALL_CHANGE_TOLERANCE:
                # Small power change - use the hunting method

                self._hunt_history.append(grid_power)
                while len(self._hunt_history) > 10:
                    self._hunt_history.pop(0)

                delta_pct = (grid_power / max_power) * _GAMMA * 100
                history_log = ', '.join(f'{h:.0f}' for h in self._hunt_history)
                LOGGER.info(f'using hunting method: gamma = {_GAMMA}, delta_pct = {delta_pct}, history = {history_log}')

                new_pct = round(max(0, min(cur_pct + delta_pct, 100)), 2)
                new_power = cur_power + grid_power * (cur_pct - new_pct) / 100
                new_power = max(0, min(new_power, max_power))

            else:
                # Large power change - use the exact method
                LOGGER.info('using exact method')

                new_power = cur_power + grid_power
                new_power = max(0, min(new_power, max_power))

                new_pct = new_power / max_power * 100
                new_pct = round(max(0, min(new_pct, 100)), 2)
                self._hunt_history = []

            power_change = new_power - cur_power
            LOGGER.info(f'max power: {max_power:.2f}')
            LOGGER.info(f'power change: {cur_power:.2f} -> {new_power:.2f} ({power_change:.2f})')
            LOGGER.info(f'grid change: {grid_power:.2f} -> {grid_power - power_change:.2f} ({power_change:.2f})')
            LOGGER.info(f'percent change: {cur_pct:.2f} -> {new_pct:.2f}')

            self._set_power_pct(new_pct, change_duration)

    # =================================================
    #  Support
    # =================================================

    def _get_power_limit(self) -> Tuple[float, bool]:
        """
        Get the power limit set on the controlling inverters.

        Returns:
            (avg(_WMaxLimPct), any(WMaxLim_Ena != 0))
        """
        power_limits: List[float] = self._get_all(self._WMaxLimPct)
        power_limits_enabled: List[bool] = [x != 0 for x in self._get_all(self._WMaxLim_Ena)]
        if len(power_limits) == 1:
            limit_enabled = power_limits_enabled[0]
            limit = power_limits[0] if limit_enabled else 100.0
            return limit, limit_enabled

        else:
            # all controlling inverters
            assert len(power_limits) == len(self._inverters_limit_proportion)
            avg_limit: float = 0.0
            for limit, limit_enabled, pr in zip(power_limits, power_limits_enabled, self._inverters_limit_proportion):
                if not limit_enabled:
                    limit = 100.0
                avg_limit += limit * pr
            return avg_limit, any(power_limits_enabled)

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
            self._set_all(self._WMaxLimPct, 100)
            self._set_all(self._WMaxLimPct_RvrtTms, change_duration)
            self._set_all(self._WMaxLim_Ena, 0)
        else:
            self._set_all(self._WMaxLimPct, pct)
            self._set_all(self._WMaxLimPct_RvrtTms, change_duration)
            self._set_all(self._WMaxLim_Ena, 1, force=True)  # force to keep alive

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

            failed: bool
            new = self._modbus[name]
            if not isinstance(new, (int, float)):
                failed = True
            else:
                failed = abs(new - value) > 10e-6
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

    def _set_all(self, names: List[str], value: int | float, *, force: bool = False) -> None:
        for name in names:
            self._set(name, value, force=force)

    def _get_all(self, names: List[str]) -> List[int | float]:
        return [
            self._get(name) for name in names
        ]

    def _get_sum(self, names: List[str]) -> int | float:
        self._logger_get_set(f'SUM {names}')
        result = sum(self._get_all(names))
        self._logger_get_set(f'SUM = {result}')
        return result
