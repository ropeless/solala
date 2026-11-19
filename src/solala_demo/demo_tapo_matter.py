import asyncio
import json
from typing import Any

import aiohttp

from solala.utils.local_config_help import config


async def request(ws: aiohttp.ClientWebSocketResponse, command: str, **kwargs: Any) -> Any:
    """
    Send a command to Matter Server and await its response.

    Args:
        ws: Connected Matter Server WebSocket.
        command: Matter Server command name.
        **kwargs: Command arguments.

    Returns:
        The response result.
    """
    message_id = 'solala-demo'
    message: dict[str, Any] = {'message_id': message_id, 'command': command}
    if kwargs:
        message['args'] = kwargs
    await ws.send_json(message)

    while True:
        response = await ws.receive(timeout=30)
        if response.type != aiohttp.WSMsgType.TEXT:
            raise RuntimeError(f'Matter WebSocket closed or failed: {response.type!r}')

        data: dict[str, Any] = json.loads(response.data)
        if data.get('message_id') != message_id:
            continue
        if data.get('message_type') == 'error' or 'error_code' in data:
            raise RuntimeError(f'Matter Server error: {data!r}')
        return data.get('result')


def show_node(node: dict[str, Any]) -> None:
    """
    Print the switch state and available electrical measurements.

    Args:
        node: Node data returned by Matter Server.
    """
    attributes = node.get('attributes', {})
    endpoint = 1

    def attribute(_cluster: int, _number: int) -> Any:
        return attributes.get(f'{endpoint}/{_cluster}/{_number}')

    print(f'Node: {node["node_id"]}, available: {node.get("available")}')
    print(f'  Device: {attributes.get("0/40/1")} {attributes.get("0/40/3")}')
    print(f'  Switch: {"on" if attribute(6, 0) else "off" if attribute(6, 0) is False else "unknown"}')

    # Matter ElectricalPowerMeasurement reports milliwatts, millivolts and milliamps.
    for label, cluster, number, divisor, unit in (
        ('Power', 144, 8, 1000, 'W'),
        ('Voltage', 144, 11, 1000, 'V'),
        ('Current', 144, 12, 1000, 'A'),
    ):
        value = attribute(cluster, number)
        print(f'  {label}: {value / divisor} {unit}' if isinstance(value, (int, float)) else f'  {label}: unavailable')

    energy = attribute(145, 1)
    if isinstance(energy, dict) and isinstance(energy.get('0'), (int, float)):
        print(f'  Energy: {energy["0"] / 1000} Wh')
    else:
        print('  Energy: unavailable')


async def main() -> None:
    """
    Inspect the commissioned P110M and optionally test its relay.

    Set action to 'on' or 'off' to test switching; 'status' makes no changes.
    """
    action = 'status'  # 'status', 'on', 'off'
    if action not in ('status', 'on', 'off'):
        raise ValueError(f'Invalid action: {action!r}')

    url = f'ws://{config.MATTER_SERVER_HOST}:{config.MATTER_SERVER_PORT}/ws'
    timeout = aiohttp.ClientTimeout(total=30)

    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.ws_connect(url) as ws:
            greeting = await ws.receive_json(timeout=15)
            if 'sdk_version' not in greeting:
                raise RuntimeError(f'Unexpected Matter Server greeting: {greeting!r}')
            print(f'Server: {greeting["sdk_version"]}')

            nodes = await request(ws, 'get_nodes')
            for node in nodes:
                show_node(node)

            if action != 'status':
                if len(nodes) != 1:
                    raise RuntimeError('Switch test requires exactly one commissioned node')
                node_id = nodes[0]['node_id']
                print(f'Sending {action} command to node {node_id}')
                await request(
                    ws, 'device_command',
                    node_id=node_id, endpoint_id=1, cluster_id=6,
                    command_name='On' if action == 'on' else 'Off', payload={},
                )
                print('Command accepted; fetching updated status')
                nodes = await request(ws, 'get_nodes')
                for node in nodes:
                    show_node(node)


if __name__ == '__main__':
    asyncio.run(main())
