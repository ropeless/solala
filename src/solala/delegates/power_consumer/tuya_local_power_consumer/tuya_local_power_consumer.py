import asyncio
import math
from functools import partial

import tinytuya

from solala.delegates.power_consumer.consumer_status import ConsumerStatus
from solala.delegates.power_consumer.power_consumer import PowerConsumer, SwitchRegister
from solala.register import AsyncCallRegister, Register, RegisterValue, check_type, check_value
from solala.register_bank import RegisterBank
from solala.utils.json_extras import JSONDict
from solala.utils.type_extras import check_bool, check_non_negative, check_num


class TuyaLocalPowerConsumer(PowerConsumer):
    """
    Access a Tuya smart plug directly using TinyTuya.

    Each operation uses a fresh socket. Blocking network operations run in a
    worker thread, and a lock serializes operations on the same device.
    """

    def __init__(
            self,
            host: str,
            device_id: str,
            local_key: str,
            *,
            version: float = 3.5,
            calibration_factor: float = 1.0,
            timeout: float = 5.0,
    ) -> None:
        """
        Configure the device without opening a connection.

        Args:
            host: Device IP address or hostname.
            device_id: Tuya device identifier.
            local_key: Device's local encryption key.
            version: Tuya LAN protocol version. This can be inferred using
                tinytuya.deviceScan(), but is configured explicitly to avoid
                depending on UDP discovery.
            calibration_factor: Multiplier for current and power readings.
            timeout: Socket timeout in seconds.
        """
        if not math.isfinite(calibration_factor) or calibration_factor <= 0:
            raise ValueError('calibration_factor must be positive and finite')
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError('timeout must be positive and finite')
        super().__init__(can_switch=True)
        self._host = host
        self._device_id = device_id
        self._local_key = local_key
        self._version = version
        self._calibration_factor = calibration_factor
        self._timeout = timeout
        self._lock = asyncio.Lock()
        self._register_bank: RegisterBank | None = None

    def _request(self, switch: bool | None = None) -> JSONDict:
        """
        Perform a blocking LAN operation and close the socket afterwards.
        """
        device = tinytuya.OutletDevice(self._device_id, self._host, self._local_key)
        device.set_version(self._version)
        device.set_socketTimeout(self._timeout)
        device.set_socketPersistent(False)
        try:
            if switch is None:
                response = device.status()
            else:
                response = device.set_status(switch, 1)
            if not isinstance(response, dict) or 'Error' in response or 'Err' in response:
                raise ConnectionError(f'Tuya LAN operation failed: {response!r}')
            return response
        finally:
            device.close()

    async def _status(self) -> JSONDict:
        async with self._lock:
            response = await asyncio.to_thread(self._request)
        dps = response.get('dps')
        if not isinstance(dps, dict):
            raise ConnectionError('Tuya LAN status response has no DPS dictionary')
        return dps

    async def get_status(self) -> ConsumerStatus:
        dps = await self._status()
        return ConsumerStatus(
            on=check_bool(dps['1']),
            current=check_non_negative(check_num(dps['18']) * 0.001 * self._calibration_factor),
            power=check_non_negative(check_num(dps['19']) * 0.1 * self._calibration_factor),
            voltage=check_non_negative(check_num(dps['20']) * 0.1),
            accumulated_energy=None,
        )

    async def _get_switch(self) -> bool:
        return check_bool((await self._status())['1'])

    async def _set_switch(self, on: bool) -> None:
        async with self._lock:
            await asyncio.to_thread(self._request, on)

    async def get_registers(self) -> RegisterBank:
        async with self._lock:
            if self._register_bank is not None:
                return self._register_bank
        dps = await self._status()
        registers: dict[str, Register] = {}
        for key, value in dps.items():
            try:
                reg_type = check_type(type(value))
            except TypeError:
                continue
            registers[key] = SwitchRegister(self) if key == '1' else AsyncCallRegister(
                partial(self._get_register_value, key), reg_type,
            )
        bank = RegisterBank(registers)
        async with self._lock:
            existing = self._register_bank
            if existing is not None:
                return existing
            self._register_bank = bank
            return bank

    async def _get_register_value(self, key: str) -> RegisterValue:
        return check_value((await self._status())[key])

    def get_connection_info(self) -> JSONDict:
        return {
            'connection': 'Tuya LAN',
            'host': self._host,
            'device_id': self._device_id,
            'version': self._version,
            'calibration_factor': self._calibration_factor,
        }

    async def close(self) -> None:
        # Each operation closes its socket; wait for any in-flight operation.
        async with self._lock:
            pass
