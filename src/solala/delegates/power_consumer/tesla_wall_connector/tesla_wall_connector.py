from functools import partial
from typing import Optional, Dict, Callable, Awaitable, AsyncIterator, Tuple, Iterable

from solala.delegates.power_consumer.power_consumer import PowerConsumer, ConsumerStatus
from solala.registers import RegisterBank, Register, check_type, RegisterType, \
    AsyncCallRegister, RegisterValue, check_value
from solala.utils.httpx_extras import async_get
from solala.utils.json_extras import JSONDict, json_dict, json_num
from solala.utils.micro_cache import AsyncMicroCache

NAME: str = 'Tesla Wall Charger'


class TeslaWallConnector(PowerConsumer):
    """
    Implementation of the CarCharger interface for Tesla Wall Connector.
    """

    def __init__(self, host: str, mac_address: str = ''):
        # noinspection HttpUrlsUsage
        self._api = f'http://{host}/api/1/'

        self._connection_status = {
            'connection': 'Tesla Wall Connector',
            'host': host,
        }
        if mac_address != '':
            self._connection_status['mac_address'] = mac_address

        # Cache `__get_vitals` for 0.1s each call
        self._cache: Callable[[], Awaitable[JSONDict]] = AsyncMicroCache(self.__get_vitals, 0.1)

        # Created on first call to `get_registers`
        self._register_bank: Optional[RegisterBank] = None

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
        data: JSONDict = await self._cache()
        return ConsumerStatus(
            voltage=json_num(data['voltageA_v']),
            current=json_num(data['currentA_a']),
        )

    def get_connection_status(self) -> JSONDict:
        return self._connection_status

    async def close(self) -> None:
        pass

    async def get_register_keys(self) -> AsyncIterator[Tuple[str, RegisterType]]:
        device_status: JSONDict = await self._cache()
        for key, value in device_status.items():
            try:
                reg_type: RegisterType = check_type(type(value))
            except TypeError:
                continue
            yield key, reg_type

    async def get_register_value(self, key: str) -> RegisterValue:
        json: JSONDict = await self._cache()
        value = json[key]
        return check_value(value)

    async def __get_vitals(self) -> JSONDict:
        url = self._api + 'vitals'
        response = await async_get(url)
        return json_dict(response.json())
