import asyncio
import json
import math
from functools import partial
from typing import Any

import aiohttp

from solala.delegates.power_consumer.consumer_status import ConsumerStatus
from solala.logger import LOGGER
from solala.utils.math_extra import safe_divide
from solala.delegates.power_consumer.power_consumer import PowerConsumer, SwitchRegister
from solala.register import AsyncCallRegister, Register, RegisterValue, check_type
from solala.register_bank import RegisterBank
from solala.utils.json_extras import JSONDict
from solala.utils.micro_cache import AsyncMicroCache


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
        self._register_bank: RegisterBank | None = None
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
            result = safe_divide(_value, 1000)
            if isinstance(result, float) and not math.isfinite(result):
                raise ConnectionError(f'Invalid Matter measurement: {_value!r}')
            return result

        # Validate required measurements before processing optional energy.
        power = measurement(144, 8)
        voltage = measurement(144, 11)
        current = measurement(144, 12)

        accumulated_energy: float | None = None
        energy_key = f'{self._endpoint_id}/145/1'
        if energy_key in attributes:
            energy = attributes[energy_key]
            try:
                if not isinstance(energy, dict) or '0' not in energy:
                    raise ValueError(f'Invalid Matter accumulated energy structure: {energy!r}')
                value = energy['0']
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise ValueError(f'Invalid Matter accumulated energy: {value!r}')
                accumulated_energy = safe_divide(value, 1000)
                if accumulated_energy < 0 or (
                        isinstance(accumulated_energy, float) and not math.isfinite(accumulated_energy)):
                    raise ValueError(f'Invalid Matter accumulated energy: {value!r}')
            except (TypeError, ValueError, OverflowError) as err:
                LOGGER.warning('Matter accumulated energy unavailable: %r', err)
                accumulated_energy = None
        return ConsumerStatus(
            on=on,
            power=power,
            voltage=voltage,
            current=current,
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
