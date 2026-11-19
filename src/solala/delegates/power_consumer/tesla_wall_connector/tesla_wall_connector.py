import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from functools import partial

import httpx

from solala.delegates.power_consumer.power_consumer import PowerConsumer, ConsumerStatus
from solala.register import check_type, RegisterType, AsyncCallRegister, RegisterValue, check_value
from solala.register_bank import RegisterBank
from solala.utils.json_extras import JSONDict, json_dict, json_num, json_bool
from solala.utils.micro_cache import AsyncMicroCache

NAME: str = 'Tesla Wall Charger'


class TeslaWallConnector(PowerConsumer):
    """
    Power consumer implementation for a Tesla Wall Connector.

    Reads the connector's local HTTP API to retrieve electrical measurements
    and expose the available data as registers.

    Important: the active power is estimated as voltage multiplied by current, assuming
    a purely resistive load.

    """

    def __init__(self, host: str, mac_address: str = ''):
        """
        Initialise the connection to a Tesla Wall Connector.

        Args:
            host: Hostname or IP address of the connector.
            mac_address: Optional MAC address included in connection information.
        """
        super().__init__(can_switch=False)

        # noinspection HttpUrlsUsage
        self._api = f'http://{host}/api/1/'
        self._client = httpx.AsyncClient()
        self._connection_info = {
            'connection': 'Tesla Wall Connector',
            'host': host,
        }
        if mac_address != '':
            self._connection_info['mac_address'] = mac_address

        # Cache `__get_vitals` for 0.01s each call
        self._cache: Callable[[], Awaitable[JSONDict]] = AsyncMicroCache(self.__get_vitals, 0.01)

        # Created on first call to `get_registers`
        self._register_bank: RegisterBank | None = None
        self._register_bank_lock = asyncio.Lock()

    async def get_registers(self) -> RegisterBank:
        reg_bank = self._register_bank
        if reg_bank is None:
            async with self._register_bank_lock:
                reg_bank = self._register_bank
                if reg_bank is None:
                    reg_bank = RegisterBank({
                        key: AsyncCallRegister(partial(self._get_register_value, key), reg_type)
                        async for key, reg_type in self._get_register_keys()
                    })
                    self._register_bank = reg_bank
        return reg_bank

    async def get_status(self) -> ConsumerStatus:
        data: JSONDict = await self._cache()
        voltage: float = json_num(data['voltageA_v'])
        current: float = json_num(data['currentA_a'])
        on: bool = json_bool(data['contactor_closed'])

        # not provided by a Tesla Wall Connector
        # TODO - accumulated_energy may be estimated by tracking "session_energy_wh"
        accumulated_energy = None

        return ConsumerStatus(
            voltage=voltage,
            current=current,
            power=voltage * current,  # assumes a pure resistive load
            on=on,
            accumulated_energy=accumulated_energy,
        )

    def get_connection_info(self) -> JSONDict:
        return self._connection_info

    async def close(self) -> None:
        await self._client.aclose()

    async def _get_switch(self) -> bool:
        return (await self.get_status()).on

    async def _set_switch(self, on: bool) -> None:
        raise NotImplementedError('Tesla Wall Connector does not support switching')

    async def _get_register_keys(self) -> AsyncIterator[tuple[str, RegisterType]]:
        """
        Get the vitals keys supported by the register system.

        Returns:
            An asynchronous iterator of register keys and their corresponding
            register types. Values with unsupported types are skipped.
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
        Get the current value of a connector vitals register.

        Args:
            key: Name of the vitals field to retrieve.

        Returns:
            The register value converted to a supported register type.
        """
        json: JSONDict = await self._cache()
        value = json[key]
        return check_value(value)

    async def __get_vitals(self) -> JSONDict:
        """
        Retrieve the connector's vitals from its local HTTP API.

        Returns:
            The vitals response as a JSON dictionary.

        Raises:
            Exception: If the HTTP request or response processing fails.
        """
        url = self._api + 'vitals'
        response = await self._client.get(url)
        return json_dict(response.json())
