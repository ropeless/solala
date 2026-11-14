from functools import partial
from collections.abc import AsyncIterator, Awaitable, Callable

from solala.delegates.power_consumer.power_consumer import PowerConsumer, ConsumerStatus
from solala.logger import LOGGER
from solala.registers import RegisterBank, check_type, RegisterType, \
    AsyncCallRegister, RegisterValue, check_value
from solala.utils.httpx_extras import async_get
from solala.utils.json_extras import JSONDict, json_dict, json_num
from solala.utils.micro_cache import AsyncMicroCache

NAME: str = 'Tesla Wall Charger'


class TeslaWallConnector(PowerConsumer):
    """
    Power consumer implementation for a Tesla Wall Connector.

    Reads the connector's local HTTP API to retrieve electrical measurements
    and expose the available vitals as registers.
    """

    def __init__(self, host: str, mac_address: str = ''):
        """
        Initialise the connection to a Tesla Wall Connector.

        Args:
            host: Hostname or IP address of the connector.
            mac_address: Optional MAC address included in connection information.
        """
        # noinspection HttpUrlsUsage
        self._api = f'http://{host}/api/1/'
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

    async def get_registers(self) -> RegisterBank:
        if self._register_bank is None:
            self._register_bank = reg_bank = RegisterBank({
                key: AsyncCallRegister((partial(self._get_register_value, key)), reg_type)
                async for key, reg_type in self._get_register_keys()
            })
            return reg_bank
        else:
            return self._register_bank

    async def get_status(self) -> ConsumerStatus:
        """
        Get the connector's electrical status.

        The active power is estimated as voltage multiplied by current, assuming
        a purely resistive load.
        """
        data: JSONDict = await self._cache()
        voltage: float = json_num(data['voltageA_v'])
        current: float = json_num(data['currentA_a'])
        return ConsumerStatus(
            voltage=voltage,
            current=current,
            power=voltage * current,  # assumes a pure resistive load
        )

    def get_connection_info(self) -> JSONDict:
        """
        Get the connector's connection details.

        Returns:
            The connection type and host, and the MAC address if supplied.
        """
        return self._connection_info

    async def close(self) -> None:
        pass

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
            The vitals response as a JSON dictionary. If the request fails, an
            error message and NaN voltage and current values are returned.
        """
        try:
            url = self._api + 'vitals'
            response = await async_get(url)
            return json_dict(response.json())
        except Exception as err:
            LOGGER.error(f'{self.__class__.__name__} {self._connection_info["host"]!r}: {err!r}')
            return {
                'error': str(err),
                'voltageA_v': float('nan'),
                'currentA_a': float('nan'),
            }
