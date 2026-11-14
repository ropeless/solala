from functools import partial
from collections.abc import AsyncIterator, Awaitable, Callable

from tuya_connector import TuyaOpenAPI

from solala.delegates.power_consumer.power_consumer import PowerConsumer, ConsumerStatus
from solala.logger import LOGGER
from solala.registers import RegisterBank, RegisterType, check_type, AsyncCallRegister, check_value, \
    RegisterValue
from solala.utils.json_extras import JSONDict, json_num
from solala.utils.micro_cache import AsyncMicroCache

API_ENDPOINT = "https://openapi.tuyaeu.com"


class TuyaPowerConsumer(PowerConsumer):

    def __init__(
            self,
            access_id: str,
            access_secret: str,
            device_id: str,
            *,
            voltage_scale_factor: float = 0.1,
            current_scale_factor: float = 0.001,
            power_scale_factor: float = 0.1,
    ) -> None:
        """
        Args:
            voltage_scale_factor: The multiplier to convert the device 'cur_voltage' to volts.
            current_scale_factor: The multiplier to convert the device 'cur_current' to amperes.
            power_scale_factor: The multiplier to convert the device 'cur_power' to watts.
        """
        self._voltage_scale_factor: float = voltage_scale_factor
        self._current_scale_factor: float = current_scale_factor
        self._power_scale_factor: float = power_scale_factor
        self._tuya = TuyaOpenAPI(
            API_ENDPOINT,
            access_id,
            access_secret,
        )
        response = self._tuya.connect()
        if not response.get('success', False):
            raise ConnectionError(response)

        self._status_url: str = f'/v1.0/iot-03/devices/{device_id}/status'
        self._connection_info: JSONDict = {
            'connection': 'Tuya',
            'access_id': access_id,
            'voltage_scale_factor': self._voltage_scale_factor,
            'current_scale_factor': self._current_scale_factor,
            'power_scale_factor': self._power_scale_factor,
        }

        # Cache `__get_device_status` for 0.01s each call.
        self._cache: Callable[[], Awaitable[JSONDict]] = AsyncMicroCache(self.__get_device_status, 0.01)

        # Created on first call to `get_registers`
        self._register_bank: RegisterBank | None = None

    async def get_registers(self) -> RegisterBank:
        if self._register_bank is None:
            self._register_bank = reg_bank = RegisterBank({
                key: AsyncCallRegister((partial(self.get_register_value, key)), reg_type)
                async for key, reg_type in self.get_register_keys()
            })
            return reg_bank
        else:
            return self._register_bank

    async def get_status(self) -> ConsumerStatus:
        device_status: JSONDict = await self._cache()
        return ConsumerStatus(
            voltage=json_num(device_status['cur_voltage']) * self._voltage_scale_factor,
            current=json_num(device_status['cur_current']) * self._current_scale_factor,
            power=json_num(device_status['cur_power']) * self._power_scale_factor,
        )

    def get_connection_info(self) -> JSONDict:
        return self._connection_info

    async def close(self) -> None:
        pass

    async def get_register_keys(self) -> AsyncIterator[tuple[str, RegisterType]]:
        device_status: JSONDict = await self._cache()
        for key, value in device_status.items():
            try:
                reg_type: RegisterType = check_type(type(value))
            except TypeError:
                continue
            yield key, reg_type

    async def get_register_value(self, key: str) -> RegisterValue:
        device_status: JSONDict = await self._cache()
        value = device_status[key]
        return check_value(value)

    async def __get_device_status(self) -> JSONDict:
        try:
            response = self._tuya.get(self._status_url)
            if not response.get('success', False):
                raise ConnectionError(response)
            return {
                item['code']: item['value']
                for item in response['result']
            }
        except Exception as err:
            LOGGER.error(f'{self.__class__.__name__} {self._connection_info["device_id"]!r}: {err!r}')
            return {
                'error': str(err),
                'cur_voltage': float('nan'),
                'cur_current': float('nan'),
                'cur_power': float('nan'),
            }
