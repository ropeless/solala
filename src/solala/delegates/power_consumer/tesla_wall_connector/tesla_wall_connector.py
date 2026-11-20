import asyncio
import math
from collections.abc import AsyncIterator, Awaitable, Callable
from functools import partial

import httpx

from solala.delegates.power_consumer.power_consumer import PowerConsumer, ConsumerStatus
from solala.logger import LOGGER
from solala.register import check_type, RegisterType, AsyncCallRegister, RegisterValue, check_value
from solala.register_bank import RegisterBank
from solala.utils.json_extras import JSONDict, json_dict, json_num, json_bool
from solala.utils.micro_cache import AsyncMicroCache

NAME: str = 'Tesla Wall Charger'


class TeslaWallConnector(PowerConsumer):
    """
    Power consumer implementation for a Tesla Wall Connector.

    Reads the connector's local HTTP API to retrieve electrical measurements
    and lifetime accumulated energy, and exposes vitals as registers.

    Important: the active power is estimated as voltage multiplied by current, assuming
    a purely resistive load.

    """

    def __init__(
            self,
            host: str,
            mac_address: str = '',
            cache_duration: float = 0.1,
    ):
        """
        Initialise the connection to a Tesla Wall Connector.

        Args:
            host: Hostname or IP address of the connector.
            mac_address: Optional MAC address included in connection information.
            cache_duration: How long to cache each API response, in seconds. The same duration
                applies independently to vitals and lifetime data. Defaults to 0.1 seconds.
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

        self._cache: Callable[[], Awaitable[JSONDict]] = AsyncMicroCache(self.__get_vitals, cache_duration)
        self._lifetime_cache: Callable[[], Awaitable[JSONDict]] = AsyncMicroCache(
            self.__get_lifetime, cache_duration
        )

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
        voltage: float = json_num(data['grid_v'])
        apparent_power = (
            json_num(data['currentA_a']) * json_num(data['voltageA_v'])
            + json_num(data['currentB_a']) * json_num(data['voltageB_v'])
            + json_num(data['currentC_a']) * json_num(data['voltageC_v'])
        )
        # Equivalent single phase current, assuming  phase-to-neutral voltage measurement
        # We are assuming a power factor or 1 (purely resistive load).
        current: float = apparent_power / voltage
        on: bool = json_bool(data['contactor_closed'])

        # Lifetime energy is optional; a failure here must not hide valid vitals.
        accumulated_energy: float | None = None
        try:
            lifetime = await self._lifetime_cache()
            raw_energy = lifetime['energy_wh']
            if not isinstance(raw_energy, bool):
                energy = json_num(raw_energy)
                if math.isfinite(energy) and energy >= 0:
                    accumulated_energy = energy
        except Exception as err:
            LOGGER.warning('Tesla Wall Connector lifetime energy unavailable: %r', err)

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

    async def __get_lifetime(self) -> JSONDict:
        """
        Retrieve lifetime counters from the connector's local HTTP API.

        Returns:
            The lifetime response as a JSON dictionary.
        """
        response = await self._client.get(self._api + 'lifetime')
        response.raise_for_status()
        return json_dict(response.json())
