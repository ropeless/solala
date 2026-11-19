import asyncio
import json
from functools import partial
from typing import Any

import aiohttp

from solala.delegates.power_consumer.consumer_status import ConsumerStatus
from solala.delegates.power_consumer.power_consumer import PowerConsumer, SwitchRegister
from solala.register import AsyncCallRegister, Register, check_type, RegisterValue, Register, RegisterValue, check_type, check_value
from solala.register_bank import RegisterBank
from solala.utils.json_extras import JSONDict
from solala.utils.micro_cache import AsyncMicroCache
from solala.utils.micro_cache import AsyncMicroCache


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
            timeout: Timeout in seconds for server operations.
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
        self._attributes_cache = AsyncMicroCache(self.__fetch_node_attributes, 0.1)
        self._register_bank_lock = asyncio.Lock()
        self._attributes_cache = AsyncMicroCache(self.__fetch_node_attributes, 0.1)
        self._register_bank_lock = asyncio.Lock()
        self._register_bank: RegisterBank | None = None
        self._status_registers: dict[str, Register] = {
            'switch': SwitchRegister(self),
            'voltage': AsyncCallRegister(self._voltage, float),
            'current': AsyncCallRegister(self._current, float),
            'power': AsyncCallRegister(self._power, float),
        }
        self._connection_info: JSONDict = {
            'connection': 'Matter',
            'host': host,
            'port': port,
            'node_id': node_id,
            'endpoint_id': endpoint_id,
            'secure': secure,
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
                ws = await self._ensure_connected()
                self._request_id += 1
                message_id = f'solala-{self._request_id}'
                message: dict[str, Any] = {'message_id': message_id, 'command': command}
                if kwargs:
                    message['args'] = kwargs
                await ws.send_json(message)
                while True:
                    response = await ws.receive(timeout=self._timeout)
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

    async def __fetch_node_attributes(self) -> dict[str, Any]:
        return await self._attributes_cache()

    async def __fetch_node_attributes(self) -> dict[str, Any]:
        """
        Retrieve attributes of the configured node, requiring it to be available.
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

    async def _node_attributes(self) -> dict[str, Any]:
        """
        Return a short-lived shared snapshot of Matter attributes.
        """
        return await self._attributes_cache()

    @staticmethod
    def _flatten_attributes(attributes: dict[str, Any]) -> dict[str, RegisterValue]:
        """
        Flatten scalar and nested dictionary attributes for diagnostic registers.

        Operational Credentials cluster (62) is excluded because it can contain
        sensitive certificate and fabric information.
        """
        result: dict[str, RegisterValue] = {}

        def add(key: str, value: Any) -> None:
            if isinstance(value, dict):
                for part, child in value.items():
                    add(f'{key}/{part}', child)
            elif type(value) in (str, int, float, bool):
                result[key] = value

        for key, value in attributes.items():
            parts = key.split('/')
            if len(parts) >= 2 and parts[1] == '62':
                continue
            add(key, value)
        return result

    async def _raw_register_value(self, key: str) -> RegisterValue:
        values = self._flatten_attributes(await self._node_attributes())
        if key not in values:
            raise ConnectionError(f'Matter diagnostic attribute {key} unavailable')
        return values[key]

    def _attribute(self, attributes: dict[str, Any], cluster: int, attribute: int) -> Any:
        key = f'{self._endpoint_id}/{cluster}/{attribute}'
        if key not in attributes:
            raise ConnectionError(f'Matter attribute {key} is unavailable')
        return attributes[key]

    async def get_status(self) -> ConsumerStatus:
        attributes = await self._node_attributes()
        on = self._attribute(attributes, 6, 0)
        if not isinstance(on, bool):
            raise ConnectionError(f'Invalid Matter switch state: {on!r}')

        def measurement(cluster: int, attribute: int) -> float:
            _value = self._attribute(attributes, cluster, attribute)
            if isinstance(_value, bool) or not isinstance(_value, (int, float)):
                raise ConnectionError(f'Invalid Matter measurement: {_value!r}')
            return float(_value) / 1000

        energy = attributes.get(f'{self._endpoint_id}/145/1')
        accumulated_energy: float | None = None
        if isinstance(energy, dict):
            value = energy.get('0')
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                accumulated_energy = float(value) / 1000
        return ConsumerStatus(
            on=on,
            power=measurement(144, 8),
            voltage=measurement(144, 11),
            current=measurement(144, 12),
            accumulated_energy=accumulated_energy,
        )

    async def _get_switch(self) -> bool:
        value = self._attribute(await self._node_attributes(), 6, 0)
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

    async def _voltage(self) -> float:
        return (await self.get_status()).voltage

    async def _current(self) -> float:
        return (await self.get_status()).current

    async def _power(self) -> float:
        return (await self.get_status()).power

    async def get_registers(self) -> RegisterBank:
        bank = self._register_bank
        if bank is None:
            async with self._register_bank_lock:
                bank = self._register_bank
                if bank is None:
                    attributes = await self._node_attributes()
                    registers = dict(self._status_registers)
                    for key, value in self._flatten_attributes(attributes).items():
                        if key in registers:
                            continue
                        try:
                            register_type = check_type(type(value))
                        except TypeError:
                            continue
                        registers[key] = AsyncCallRegister(
                            partial(self._get_raw_register, key), register_type,
                        )
                    bank = RegisterBank(registers)
                    self._register_bank = bank
        return bank

    @staticmethod
    def _flatten_attributes(attributes: dict[str, Any]) -> dict[str, RegisterValue]:
        """Flatten nested Matter attributes into scalar diagnostic registers."""
        flattened: dict[str, RegisterValue] = {}

        def visit(key: str, value: Any) -> None:
            if isinstance(value, dict):
                for child, item in value.items():
                    visit(f'{key}/{child}', item)
            elif isinstance(value, (str, int, float, bool)):
                flattened[key] = check_value(value)

        for key, value in attributes.items():
            visit(key, value)
        return flattened

    async def _get_raw_register(self, key: str) -> RegisterValue:
        attributes = await self._node_attributes()
        values = self._flatten_attributes(attributes)
        if key not in values:
            raise ConnectionError(f'Matter diagnostic attribute {key} is unavailable')
        return values[key]

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
