from collections.abc import Iterable
from contextlib import contextmanager
from typing import Iterator

from solala.delegates.power_controller.modbus_power_controller.modbus import Modbus, ModbusDevice
from solala.delegates.power_controller.modbus_power_controller.modbus_register_access import ModbusError
from solala.delegates.power_controller.power_controller import PowerController, PowerStatus
from solala.logger import LOGGER
from solala.registers import RegisterBank, Register, AsyncCallRegister
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
    Power controller that monitors and controls a power system using Modbus.

    The controller uses a master inverter, optional slave inverters, and a grid
    meter. Battery control is performed through the master inverter.

    By default, inverter power curtailment is applied only to the master inverter.
    Set `power_control_slaves` to True to apply power curtailment to all inverters.
    """

    def __init__(
            self,
            modbus: Modbus,
            *,
            master: str = 'master',
            meter: str = 'meter',
            slaves: Iterable[str] = (),
            mac_addr_lookup: dict[str, str] | None = None,
            power_control_slaves: bool = False,
    ) -> None:
        """
        Initialise a Modbus power controller.

        Args:
            modbus: Modbus connection providing access to the power system devices.
            master: Logical name of the master inverter in `modbus`.
            meter: Logical name of the grid meter in `modbus`.
            slaves: Logical names of any slave inverters in `modbus`.
            mac_addr_lookup: Optional mapping of device host addresses to MAC addresses,
                used when reporting connection information.
            power_control_slaves: Whether inverter power curtailment should also be
                applied to slave inverters. If False, curtailment is applied only
                to the master inverter.
        """
        self._modbus: Modbus = modbus
        self._master = master
        self._slaves = list(slaves)
        self._inverters = [self._master] + self._slaves
        self._meter = meter
        self._log_set_get: bool = False
        self._hunt_history: list[float] = []
        self._is_force_discharge: bool = False

        # Important registers
        self._ChaState: str = f'{master}/ChaState'
        self._charge_power: str = f'{master}/module/3/DCW'
        self._discharge_power: str = f'{master}/module/4/DCW'
        self._solar_power: list[str] = [f'{inverter}/module/{i}/DCW' for inverter in self._inverters for i in [1, 2]]
        self._grid_power: str = f'{meter}/W'
        self._inverter_power: list[str] = [f'{inverter}/W' for inverter in self._inverters]

        self._accumulated_grid_import: str = f'{meter}/TotWhImp'
        self._accumulated_grid_export: str = f'{meter}/TotWhExp'
        self._accumulated_solar_energy: list[str] = [f'{inverter}/module/{i}/DCWH' for inverter in self._inverters for i
                                                     in [1, 2]]
        self._accumulated_charge_energy: str = f'{master}/module/3/DCWH'
        self._accumulated_discharge_energy: str = f'{master}/module/4/DCWH'
        # self._accumulated_inverter_power: list[str] = [f'{inverter}/ActWh' for inverter in self._inverters]

        if power_control_slaves:
            self._power_controllers: list[str] = self._inverters
        else:
            self._power_controllers: list[str] = [master]
        self._WMaxLim_Ena: list[str] = [f'{inverter}/WMaxLim_Ena' for inverter in self._power_controllers]
        self._WMaxLimPct: list[str] = [f'{inverter}/WMaxLimPct' for inverter in self._power_controllers]
        self._WMaxLimPct_RvrtTms: list[str] = [f'{inverter}/WMaxLimPct_RvrtTms' for inverter in self._power_controllers]

        self._InWRte: str = f'{master}/InWRte'
        self._OutWRte: str = f'{master}/OutWRte'
        self._StorCtl_Mod: str = f'{master}/StorCtl_Mod'
        self._MinRsvPct: str = f'{master}/MinRsvPct'
        self._ChaGriSet: str = f'{master}/ChaGriSet'

        # Save the connection status
        devices_record: dict[str, JSONValue] = {}
        unnamed_device: JSONDict | None = None
        device_name: str | None
        device: ModbusDevice
        for device_name, device in modbus.devices().items():
            host: str = device.client.comm_params.host
            device_record: dict[str, JSONValue] = {'host': host}
            if mac_addr_lookup is not None:
                mac_address: str | None = mac_addr_lookup.get(host)
                if mac_address is not None and mac_address != '':
                    device_record['mac_address'] = mac_address
            device_record['device'] = device.device_id
            if device_name is None:
                unnamed_device = device_record
            else:
                devices_record[device_name] = device_record
        self._connection_info: dict[str, JSONValue] = {
            'connection': 'Modbus',
            'devices': devices_record,
        }
        if unnamed_device is not None:
            self._connection_info['unnamed_device'] = unnamed_device

        registers: dict[str, Register] = dict(self._modbus.registers)
        registers[_INVERTER_LIMIT_NAME] = AsyncCallRegister(self.get_inverter_limit, float)
        self._registers: RegisterBank = RegisterBank(registers)

    def connect(self) -> None:
        """
        Delegate `connect` to Modbus clients.
        """
        self._modbus.connect()

    def get_connection_info(self) -> JSONDict:
        return self._connection_info

    async def get_inverter_limit(self) -> float:
        return sum(await self._get_inverter_limit_array())

    async def close(self) -> None:
        """
        Delegate `close` to Modbus clients.
        """
        self._modbus.close()

    async def get_registers(self) -> RegisterBank:
        return self._registers

    async def get_status(self) -> PowerStatus:
        state_of_charge = await self._get(self._ChaState)
        charge_power = await self._get(self._charge_power)
        discharge_power = await self._get(self._discharge_power)
        solar_power = await self._get_sum(self._solar_power)
        grid_power = await self._get(self._grid_power)

        accumulated_grid_import = await self._get(self._accumulated_grid_import)
        accumulated_grid_export = await self._get(self._accumulated_grid_export)
        accumulated_solar_energy = await self._get_sum(self._accumulated_solar_energy)
        accumulated_charge_energy = await self._get(self._accumulated_charge_energy)
        accumulated_discharge_energy = await self._get(self._accumulated_discharge_energy)
        # accumulated_inverter_power = await self._get_sum(self._accumulated_inverter_power)

        battery_power = charge_power - discharge_power
        house_power = grid_power + solar_power - battery_power

        power_limit, power_limit_enabled = await self._get_power_limit()

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

    async def enable_battery(self) -> None:
        with self._log_it('enable_battery'):
            await self._set(self._StorCtl_Mod, 0)
            await self._set(self._InWRte, 100)
            await self._set(self._OutWRte, 100)
            await self._set(self._ChaGriSet, 0)
            await self._set(self._MinRsvPct, _DEFAULT.MinRsvPct)
            self._is_force_discharge = False

    async def disable_battery(self) -> None:
        with self._log_it('disable_battery'):
            await self._set(self._StorCtl_Mod, 0)  # Temp to avoid any invalid value exception
            await self._set(self._InWRte, 0)
            await self._set(self._OutWRte, 0)
            await self._set(self._StorCtl_Mod, 3)
            await self._set(self._ChaGriSet, 0)
            await self._set(self._MinRsvPct, _DEFAULT.MinRsvPct)
            self._is_force_discharge = False

    async def force_charge(self) -> None:
        with self._log_it('force_charge'):
            await self._set(self._StorCtl_Mod, 0)  # Temp to avoid any invalid value exception
            await self._set(self._InWRte, 100)
            await self._set(self._OutWRte, 0)  # Don't try to discharge at the same time as charging
            await self._set(self._StorCtl_Mod, 3)
            await self._set(self._ChaGriSet, 1)
            await self._set(self._MinRsvPct, 100)
            self._is_force_discharge = False

    async def force_discharge(self) -> None:
        with self._log_it('force_discharge'):
            await self._set(self._StorCtl_Mod, 0)  # Temp to avoid any invalid value exception
            await self._set(self._InWRte, -100)  # negative flow
            await self._set(self._OutWRte, 100)
            await self._set(self._StorCtl_Mod, 3)
            await self._set(self._ChaGriSet, 0)
            await self._set(self._MinRsvPct, _DEFAULT.MinRsvPct)
            self._is_force_discharge = True

    async def charge_only(self) -> None:
        with self._log_it('charge_only'):
            await self._set(self._StorCtl_Mod, 0)  # Temp to avoid any invalid value exception
            await self._set(self._InWRte, 100)
            await self._set(self._OutWRte, 0)
            await self._set(self._StorCtl_Mod, 3)
            await self._set(self._ChaGriSet, 0)
            await self._set(self._MinRsvPct, _DEFAULT.MinRsvPct)
            self._is_force_discharge = False

    async def discharge_only(self) -> None:
        with self._log_it('discharge_only'):
            await self._set(self._StorCtl_Mod, 0)  # Temp to avoid any invalid value exception
            await self._set(self._InWRte, 0)
            await self._set(self._OutWRte, 100)
            await self._set(self._StorCtl_Mod, 3)
            await self._set(self._ChaGriSet, 0)
            await self._set(self._MinRsvPct, _DEFAULT.MinRsvPct)
            self._is_force_discharge = False

    # =================================================
    #  Grid Export Control
    # =================================================

    async def _get_inverter_limit_array(self) -> list[float]:
        """
        Get the effective output power limit for each inverter.

        The limit is the lower of the inverter's maximum power rating and
        its rated power.

        Returns:
            The output power limits in watts, in inverter order,
            coindexed with `self._inverters`.
        """
        return [
            min(
                await self._get(f'{inverter}/WMax'),
                await self._get(f'{inverter}/WRtg'),
            )
            for inverter in self._inverters
        ]

    async def enable_inverter(self) -> None:
        with self._log_it('enable_inverter'):
            await self._set_power_pct(100)

    async def disable_inverter(self, *, change_duration: int) -> None:
        with self._log_it('disable_inverter'):
            await self._set_power_pct(0, change_duration)

    async def zero_export(self, *, change_duration: int) -> None:
        """
        Curtail the inverter output power to minimise grid export.

        The controller adjusts the inverter limit to balance solar generation
        against consumption. Small power differences are handled using a
        hunting method, while larger differences use a direct adjustment.

        This method may need to be called repeatedly as consumption changes
        or the inverter setting reverts after the requested duration.
        """
        with self._log_it('zero_export'):
            cur_pct: float
            cur_pct, _ = await self._get_power_limit()
            grid_power: float = await self._get(self._grid_power)
            max_power: float = await self.get_inverter_limit()
            cur_power: float = await self._get_sum(self._inverter_power)

            # Include normal battery discharge when calculating available power.
            # Forced discharge is handled separately.
            if not self._is_force_discharge:
                discharge_power = await self._get(self._discharge_power)
                cur_power += discharge_power

            abs_grid_power = abs(grid_power)
            # Account for existing output if the inverter is oversupplying.
            max_power = max(max_power, cur_power)

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

            await self._set_power_pct(new_pct, change_duration)

    # =================================================
    #  Support
    # =================================================

    async def _get_power_limit(self) -> tuple[float, bool]:
        """
        Get the power limit set on the controlling inverters.

        Returns:
            tuple[float, bool]: The effective inverter power limit as a percentage
            and whether a power limit is enabled. When multiple inverters are
            controlled, the percentage is weighted by each inverter's rated
            output power.
        """
        power_limits: list[float] = await self._get_all(self._WMaxLimPct)
        power_limits_enabled: list[bool] = [x != 0 for x in await self._get_all(self._WMaxLim_Ena)]
        if len(power_limits) == 1:
            limit_enabled = power_limits_enabled[0]
            limit = power_limits[0] if limit_enabled else 100.0
            return limit, limit_enabled

        else:
            # all controlling inverters
            inverter_limits: list[float] = await self._get_inverter_limit_array()
            assert len(power_limits) == len(inverter_limits)

            total_limit: float = sum(inverter_limits)
            avg_limit: float = 0.0
            for limit, limit_enabled, inverter_limit in zip(power_limits, power_limits_enabled, inverter_limits):
                if not limit_enabled:
                    limit = 100.0
                pr = inverter_limit / total_limit
                avg_limit += limit * pr
            return avg_limit, any(power_limits_enabled)

    @contextmanager
    def _log_it(self, name: str) -> Iterator[None]:
        """
        Enable register-operation logging for the duration of the context.

        Args:
            name: Name of the operation to include in the log messages.
        """
        self._log_set_get = True
        LOGGER.info(f'{_START} {name}')
        yield
        LOGGER.info(f'{_STOP} {name}')
        self._log_set_get = False

    def _logger_get_set(self, message: str) -> None:
        """
        Log a register operation when register-operation logging is enabled.

        Args:
            message: Message describing the register operation.
        """
        if self._log_set_get:
            LOGGER.info(message)

    async def _set_power_pct(self, pct: float, change_duration: int = _DEFAULT.WMaxLimPct_RvrtTms) -> None:
        """
        Set the inverter output limit and its automatic reversion duration.

        A limit of 100% or greater disables power curtailment. Lower values implement
        power curtailment.

        Args:
            pct: Inverter output limit as a percentage of rated power.
            change_duration: Requested duration in seconds before the setting reverts.
        """
        if pct >= 100:
            await self._set_all(self._WMaxLimPct, 100)
            await self._set_all(self._WMaxLimPct_RvrtTms, change_duration)
            await self._set_all(self._WMaxLim_Ena, 0)
        else:
            await self._set_all(self._WMaxLimPct, pct)
            await self._set_all(self._WMaxLimPct_RvrtTms, change_duration)
            await self._set_all(self._WMaxLim_Ena, 1, force=True)  # force to keep alive

    async def _set(self, name: str, value: int | float, *, force: bool = False) -> None:
        """
        Set a register value and verify the change.

        The old and new values are logged when register logging is enabled.
        Modbus write errors and verification failures are logged.

        Args:
            name: Name of the register to update.
            value: Value to write.
            force: Write the value even if it is unchanged.
        """
        old = await self._modbus.get(name)
        if not force and old == value:
            # No change needed
            self._logger_get_set(f'SET {name}: {old!r} -> {value!r} UNCHANGED')
        else:
            # Make the change
            try:
                await self._modbus.set(name, value)
            except ModbusError as err:
                LOGGER.error(f'SET {name}: {old!r} -> {value!r} ERROR: {err}')
                LOGGER.error(f'Modbus message: {err.modbus_message!r}')
                return

            failed: bool
            new = await self._modbus.get(name)
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

    async def _get(self, name: str) -> int | float:
        """
        Read a register value and ensure it is numeric.

        Args:
            name: Name of the register to read.

        Returns:
            The register value as an integer or float.

        Raises:
            TypeError: If the register value is not numeric.
        """
        value = await self._modbus.get(name)
        self._logger_get_set(f'GET {name}: {value!r}')
        if not isinstance(value, (int, float)):
            msg = f'getting register {name!r}: Expected int or float, got {type(value)}'
            LOGGER.error(msg)
            raise TypeError(msg)
        return value

    async def _set_all(self, names: list[str], value: int | float, *, force: bool = False) -> None:
        """
        Set the same value on each register in a list.

        Args:
            names: Names of the registers to update.
            value: Value to write to each register.
            force: Write each value even if it is unchanged.
        """
        for name in names:
            await self._set(name, value, force=force)

    async def _get_all(self, names: list[str]) -> list[int | float]:
        """
        Read a list of registers.

        Args:
            names: Names of the registers to read.

        Returns:
            Register values are returned coindexed with the given names.
        """
        return [
            await self._get(name) for name in names
        ]

    async def _get_sum(self, names: list[str]) -> int | float:
        """
        Read and sum a list of numeric registers.

        Args:
            names: Names of the registers to read and sum.

        Returns:
            The sum of the register values.
        """
        self._logger_get_set(f'SUM {names}')
        result = sum(await self._get_all(names))
        self._logger_get_set(f'SUM = {result}')
        return result
