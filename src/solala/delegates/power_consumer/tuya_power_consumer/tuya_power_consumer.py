import asyncio
import math
from collections.abc import AsyncIterator, Awaitable, Callable
from functools import partial

from tuya_connector import TuyaOpenAPI

from solala.delegates.power_consumer.power_consumer import PowerConsumer, ConsumerStatus, SwitchRegister
from solala.logger import LOGGER
from solala.register import RegisterType, check_type, AsyncCallRegister, check_value, RegisterValue, Register
from solala.register_bank import RegisterBank
from solala.utils.json_extras import JSONDict
from solala.utils.micro_cache import AsyncMicroCache
from solala.utils.type_extras import check_num, check_bool

API_ENDPOINT = "https://openapi.tuyaeu.com"


class TuyaPowerConsumer(PowerConsumer):
    """
    Power consumer implementation for a device connected through the Tuya IoT API.

    Retrieves device status and exposes supported status fields as registers.

    API failures propagate to callers without caching synthetic measurements.
    A failed request can be retried on the next access.
    """

    def __init__(
            self,
            access_id: str,
            access_secret: str,
            device_id: str,
            *,
            voltage_scale_factor: float = 0.1,
            current_scale_factor: float = 0.001,
            power_scale_factor: float = 0.1,
            cache_duration: float = 300,
            include_accumulated_energy: bool = False,
    ) -> None:
        """
        Configure the Tuya API client and device measurements.

        Args:
            access_id: Tuya project access ID.
            access_secret: Tuya project access secret.
            device_id: Identifier of the Tuya device.
            voltage_scale_factor: Multiplier converting the device's
                'cur_voltage' value to volts.
            current_scale_factor: Multiplier converting the device's
                'cur_current' value to amperes.
            power_scale_factor: Multiplier converting the device's
                'cur_power' value to watts.
            cache_duration: How long to cache the device status. Use this to reduce how often the
                API is called. The default value is 300 seconds (5 minutes).
            include_accumulated_energy: Whether to report Tuya's 'add_ele' value as Wh.
        """
        super().__init__(can_switch=True)
        self._include_accumulated_energy = include_accumulated_energy
        self._command_url: str = f'/v1.0/iot-03/devices/{device_id}/commands'
        self._voltage_scale_factor: float = voltage_scale_factor
        self._current_scale_factor: float = current_scale_factor
        self._power_scale_factor: float = power_scale_factor
        self._tuya = TuyaOpenAPI(
            API_ENDPOINT,
            access_id,
            access_secret,
        )
        self._connected: bool = False
        self._connect_lock = asyncio.Lock()
        self._status_url: str = f'/v1.0/iot-03/devices/{device_id}/status'
        self._connection_info: JSONDict = {
            'connection': 'Tuya',
            'access_id': access_id,
            'device_id': device_id,
            'voltage_scale_factor': self._voltage_scale_factor,
            'current_scale_factor': self._current_scale_factor,
            'power_scale_factor': self._power_scale_factor,
            'include_accumulated_energy': include_accumulated_energy,
        }

        # Cache Tuya device status for the requested duration to limit cloud API usage.
        self._cache = AsyncMicroCache(self.__get_device_status, cache_duration)

        # Created on first call to `get_registers`
        self._register_bank: RegisterBank | None = None
        self._register_bank_lock = asyncio.Lock()

    async def _connect(self) -> None:
        """
        Establish the Tuya API connection without blocking the event loop.
        """
        if not self._connected:
            async with self._connect_lock:
                if not self._connected:
                    response = await asyncio.to_thread(self._tuya.connect)
                    if not response.get('success', False):
                        raise ConnectionError(response)
                    self._connected = True

    async def get_registers(self) -> RegisterBank:
        reg_bank = self._register_bank
        if reg_bank is None:
            async with self._register_bank_lock:
                reg_bank = self._register_bank
                if reg_bank is None:
                    registers: dict[str, Register] = {}
                    async for key, reg_type in self._get_register_keys():
                        registers[key] = AsyncCallRegister(partial(self._get_register_value, key), reg_type)
                    registers['switch_1'] = SwitchRegister(self)
                    reg_bank = RegisterBank(registers)
                    self._register_bank = reg_bank
        return reg_bank

    async def get_status(self) -> ConsumerStatus:
        device_status: JSONDict = await self._cache()
        voltage: float = check_num(device_status['cur_voltage']) * self._voltage_scale_factor
        current: float = check_num(device_status['cur_current']) * self._current_scale_factor
        power: float = check_num(device_status['cur_power']) * self._power_scale_factor
        on: bool = check_bool(device_status['switch_1'])
        accumulated_energy: float | None = None
        if self._include_accumulated_energy:
            try:
                raw_energy = device_status['add_ele']
                if isinstance(raw_energy, bool):
                    raise ValueError('Tuya accumulated energy must be numeric, not boolean')
                energy = check_num(raw_energy)
                if not math.isfinite(energy) or energy < 0:
                    raise ValueError(f'Invalid Tuya accumulated energy: {energy!r}')
                accumulated_energy = energy
            except (KeyError, TypeError, ValueError) as err:
                LOGGER.warning('Tuya accumulated energy unavailable: %r', err)
        return ConsumerStatus(
            voltage=voltage,
            current=current,
            power=power,
            on=on,
            accumulated_energy=accumulated_energy,
        )

    async def _get_switch(self) -> bool:
        """
        Return the switch state reported by Tuya.
        """
        device_status: JSONDict = await self._cache()
        return check_bool(device_status['switch_1'])

    async def _set_switch(self, on: bool) -> None:
        """
        Set the Tuya switch state.

        Args:
            on: True to switch on, False to switch off.
        """
        await self._connect()
        payload = {'commands': [{'code': 'switch_1', 'value': on}]}
        response = await asyncio.to_thread(self._tuya.post, self._command_url, payload)
        if not response.get('success', False):
            raise ConnectionError(response)
        await self._cache.invalidate()

    def get_connection_info(self) -> JSONDict:
        return self._connection_info

    async def close(self) -> None:
        pass

    async def _get_register_keys(self) -> AsyncIterator[tuple[str, RegisterType]]:
        """
        Get the device status fields supported by the register system.

        Returns:
            An asynchronous iterator of status field names and their
            corresponding register types. Fields with unsupported value types
            are skipped.
        """
        device_status: JSONDict = await self._cache()
        for key, value in device_status.items():
            try:
                reg_type: RegisterType = check_type(type(value))
            except TypeError:
                continue
            yield key, reg_type

    async def _get_register_value(self, key: str) -> RegisterValue:
        """
        Get the current value of a device status field.

        Args:
            key: Name of the status field to retrieve.

        Returns:
            The field value converted to a supported register type.
        """
        device_status: JSONDict = await self._cache()
        value = device_status[key]
        return check_value(value)

    async def __get_device_status(self) -> JSONDict:
        """
        Retrieve the device status from the Tuya IoT API.

        Returns:
            A dictionary mapping status codes to values.

        Raises:
            ConnectionError: If the Tuya API reports an unsuccessful response.
            Exception: If connecting or requesting device status fails.
        """
        await self._connect()
        response = await asyncio.to_thread(self._tuya.get, self._status_url)
        if not response.get('success', False):
            raise ConnectionError(response)
        return {
            item['code']: item['value']
            for item in response['result']
        }
