import asyncio
import json
from functools import partial
from typing import Any, Mapping

import aiohttp

from solala.delegates.power_consumer.consumer_status import ConsumerStatus
from solala.delegates.power_consumer.power_consumer import PowerConsumer, SwitchRegister
from solala.logger import LOGGER
from solala.register import AsyncCallRegister, Register, RegisterValue, check_type
from solala.register_bank import RegisterBank
from solala.utils.json_extras import JSONDict
from solala.utils.math_extra import safe_divide
from solala.utils.micro_cache import AsyncMicroCache
from solala.utils.type_extras import check_num, check_non_negative

# Exclude potentially sensitive Matter clusters from diagnostic registers.
# Comment out individual entries to expose their attributes when appropriate.
_EXCLUDED_CLUSTERS = {
    31,  # Access Control
    # 48,  # General Commissioning
    49,  # Network Commissioning
    53,  # Thread Network Diagnostics
    # 54,  # Wi-Fi Network Diagnostics
    62,  # Operational Credentials
}


class _ATTRIBUTE_FUNCTION:
    """
    A function from cluster, attribute to the value at that name.
    """

    def __init__(self, endpoint_id: int, attributes: JSONDict) -> None:
        self._endpoint_id = endpoint_id
        self._attributes = attributes

    def __call__(self, cluster: int, attribute: int, *sub_keys: int) -> Any:
        """
        Raises:
            ConnectionError if the attribute is not available.
        """
        key = f'{self._endpoint_id}/{cluster}/{attribute}'
        result = self._attributes.get(key)
        if result is None:
            raise ConnectionError(f'Matter attribute {key} is unavailable')
        for sub_key in sub_keys:
            if not isinstance(result, Mapping):
                raise ConnectionError(f'Matter attribute {key} is not a dictionary')
            key = f'{key}/{sub_key}'
            result = result.get(str(sub_key))
            if result is None:
                raise ConnectionError(f'Matter attribute {key} is unavailable')

        return result


class MatterPowerConsumer(PowerConsumer):
    """
    Monitor and switch a Matter device through a Matter Server WebSocket.

    The server address and optional authentication token are supplied by the caller.
    All electrical measurements are converted to V, A, W, and Wh.
    """

    def __init__(
            self,
            host: str,
            port: int,
            *,
            node_id: int,
            endpoint_id: int,
            token: str | None = None,
            secure: bool = False,
            timeout: float = 30,
            cache_duration: float = 0.1,
    ) -> None:
        """
        Configure a Matter Server connection without opening it.

        Args:
            host: Matter Server hostname or IP address.
            port: Matter Server WebSocket port.
            node_id: Commissioned Matter node identifier.
            endpoint_id: Endpoint containing the device's electrical clusters.
            token: Optional bearer token for an authenticated server.
            secure: Whether to use TLS (wss rather than ws).
            timeout: Seconds allowed for WebSocket setup, sending the command,
                and receiving its matching reply after acquiring the request lock.
            cache_duration: How long to reuse node attributes, in seconds.
        """
        super().__init__(can_switch=True)
        self._url = f'{"wss" if secure else "ws"}://{host}:{port}/ws'
        self._node_id = node_id
        self._endpoint_id = endpoint_id
        self._timeout = timeout
        self._headers = {'Authorization': f'Bearer {token}'} if token is not None else {}
        self._session: aiohttp.ClientSession | None = None
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._lock = asyncio.Lock()
        self._request_id = 0
        self._attributes_cache = AsyncMicroCache(self.__fetch_node_attributes, cache_duration)
        self._register_bank_lock = asyncio.Lock()
        self._register_bank: RegisterBank | None = None
        self._connection_info: JSONDict = {
            'connection': 'Matter',
            'host': host,
            'port': port,
            'node_id': node_id,
            'endpoint_id': endpoint_id,
            'secure': secure,
            'timeout': timeout,
            'cache_duration': cache_duration,
        }

    async def _ensure_connected(self) -> aiohttp.ClientWebSocketResponse:
        """
        Open the WebSocket and validate the Matter Server greeting.
        """
        if self._ws is not None and not self._ws.closed:
            return self._ws
        await self._disconnect()
        session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self._timeout))
        self._session = session
        try:
            ws = await session.ws_connect(self._url, headers=self._headers)
            self._ws = ws
            greeting = await ws.receive_json(timeout=self._timeout)
            if not isinstance(greeting, dict) or 'sdk_version' not in greeting:
                raise ConnectionError(f'Unexpected Matter Server greeting: {greeting!r}')
            return ws
        except BaseException:
            await self._disconnect()
            raise

    async def _request(self, command: str, **kwargs: Any) -> Any:
        """
        Send a command and await its matching response, ignoring server events.
        """
        async with self._lock:
            try:
                async with asyncio.timeout(self._timeout):
                    ws = await self._ensure_connected()
                    self._request_id += 1
                    message_id = f'solala-{self._request_id}'
                    message: dict[str, Any] = {'message_id': message_id, 'command': command}
                    if kwargs:
                        message['args'] = kwargs
                    await ws.send_json(message)
                    while True:
                        response = await ws.receive()
                        if response.type != aiohttp.WSMsgType.TEXT:
                            raise ConnectionError(f'Matter WebSocket closed: {response.type!r}')
                        data = json.loads(response.data)
                        if data.get('message_id') != message_id:
                            continue
                        if data.get('message_type') == 'error' or 'error_code' in data:
                            raise ConnectionError(f'Matter Server error: {data!r}')
                        return data.get('result')
            except BaseException:
                await self._disconnect()
                raise

    async def __fetch_node_attributes(self) -> JSONDict:
        """
        Retrieve attributes of the configured node, requiring it to be available.

        Example return value:
        ```
        {
            '1/6/0': True,
            '1/144/8': 125000,
            '1/144/11': 240000,
            '1/145/1': {
                '0': 123456,
                '1': 0,
            },
        }
        ```

        Returns:
            a dictionary of Matter attributes, and some attribute values can themselves be nested dictionaries.
            The outer dictionary is flat, with slash-separated keys identifying the endpoint, cluster, and attribute.
        """
        nodes = await self._request('get_nodes')
        if not isinstance(nodes, list):
            raise ConnectionError(f'Invalid Matter node list: {nodes!r}')
        for node in nodes:
            if isinstance(node, dict) and node.get('node_id') == self._node_id:
                if not node.get('available', False):
                    raise ConnectionError(f'Matter node {self._node_id} is unavailable')
                attributes = node.get('attributes')
                if not isinstance(attributes, dict):
                    raise ConnectionError('Matter node has no attribute dictionary')
                return attributes
        raise ConnectionError(f'Matter node {self._node_id} not found')

    async def _node_attributes(self) -> JSONDict:
        """
        Return a short-lived shared snapshot of Matter attributes.
        """
        return await self._attributes_cache()

    async def _attribute(self) -> _ATTRIBUTE_FUNCTION:
        """
        Return a short-lived shared snapshot of Matter attributes as a function from
        cluster, attribute, etc to the value at that path.
        """
        attributes: JSONDict = await self._node_attributes()
        return _ATTRIBUTE_FUNCTION(self._endpoint_id, attributes)

    @staticmethod
    def _flatten_attributes(attributes: JSONDict) -> dict[str, RegisterValue]:
        """
        Flatten scalar and nested dictionary attributes for diagnostic registers.

        Exclude clusters listed in _EXCLUDED_CLUSTERS to avoid exposing
        potentially sensitive commissioning, network, and fabric information.
        """
        result: dict[str, RegisterValue] = {}

        def add(_key: str, _value: Any) -> None:
            if isinstance(_value, dict):
                for part, child in _value.items():
                    add(f'{_key}/{part}', child)
            elif type(_value) in (str, int, float, bool):
                result[_key] = _value

        for key, value in attributes.items():
            parts = key.split('/')
            if len(parts) >= 3 and parts[1].isdigit() and int(parts[1]) in _EXCLUDED_CLUSTERS:
                continue
            add(key, value)
        return result

    async def _raw_register_value(self, key: str) -> RegisterValue:
        values = self._flatten_attributes(await self._node_attributes())
        if key not in values:
            raise ConnectionError(f'Matter diagnostic attribute {key} unavailable')
        return values[key]

    @staticmethod
    def _optional_accumulated_energy(attribute: _ATTRIBUTE_FUNCTION) -> int | float | None:
        """
        Read optional imported energy without failing required measurements.

        A missing attribute means energy is unavailable. Malformed energy is
        logged and omitted so valid switch, power, voltage, and current readings
        can still be returned.

        Args:
            attribute: snapshot _ATTRIBUTE_FUNCTION to get attribute values.
        """
        try:
            energy = attribute(145, 1, 0)
        except ConnectionError:
            # energy reading not available
            return None

        try:
            value = check_num(energy)
            converted_energy = safe_divide(value, 1000)
            return check_non_negative(converted_energy)

        except (TypeError, ValueError, OverflowError) as err:
            LOGGER.warning(f'Matter accumulated energy unavailable: {err!r}')
            return None

    async def get_status(self) -> ConsumerStatus:
        attribute: _ATTRIBUTE_FUNCTION = await self._attribute()
        on = attribute(6, 0)
        if not isinstance(on, bool):
            raise ConnectionError(f'Invalid Matter switch state: {on!r}')

        def measurement(_cluster: int, _attribute: int) -> float:
            _value = attribute(_cluster, _attribute)
            try:
                m = check_num(_value)
                result = safe_divide(m, 1000)
                return check_non_negative(result)
            except (TypeError, ValueError, OverflowError) as err:
                raise ConnectionError(f'Invalid Matter measurement: {_value!r}') from err

        # Validate required measurements before processing optional energy.
        power = measurement(144, 8)
        voltage = measurement(144, 11)
        current = measurement(144, 12)
        # Attempt to ascertain accumulated energy reading.
        accumulated_energy = self._optional_accumulated_energy(attribute)

        return ConsumerStatus(
            on=on,
            power=power,
            voltage=voltage,
            current=current,
            accumulated_energy=accumulated_energy,
        )

    async def _get_switch(self) -> bool:
        attribute: _ATTRIBUTE_FUNCTION = await self._attribute()
        value = attribute(6, 0)
        if not isinstance(value, bool):
            raise ConnectionError(f'Invalid Matter switch state: {value!r}')
        return value

    async def _set_switch(self, on: bool) -> None:
        await self._request(
            'device_command',
            node_id=self._node_id,
            endpoint_id=self._endpoint_id,
            cluster_id=6,
            command_name='On' if on else 'Off',
            payload={},
        )
        await self._attributes_cache.invalidate()

    async def get_registers(self) -> RegisterBank:
        bank = self._register_bank
        if bank is None:
            async with self._register_bank_lock:
                bank = self._register_bank
                if bank is None:
                    attributes = await self._node_attributes()
                    registers: dict[str, Register] = {}
                    for key, value in self._flatten_attributes(attributes).items():
                        if key in registers:
                            continue
                        try:
                            register_type = check_type(type(value))
                        except TypeError:
                            continue
                        if key == f'{self._endpoint_id}/6/0' and register_type is bool:
                            registers[key] = SwitchRegister(self)
                        else:
                            registers[key] = AsyncCallRegister(
                                partial(self._raw_register_value, key), register_type,
                            )
                    bank = RegisterBank(registers)
                    self._register_bank = bank
        return bank

    def get_connection_info(self) -> JSONDict:
        return self._connection_info

    async def _disconnect(self) -> None:
        ws, session = self._ws, self._session
        self._ws = None
        self._session = None
        if ws is not None:
            await ws.close()
        if session is not None:
            await session.close()

    async def close(self) -> None:
        async with self._lock:
            await self._disconnect()
