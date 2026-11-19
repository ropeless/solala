import asyncio
import json
from typing import Any

import aiohttp

from solala.utils.local_config_help import config


async def request(ws: aiohttp.ClientWebSocketResponse, command: str, **args: Any) -> Any:
    """
    Send a Matter Server command and wait for its matching response.
    """
    message_id = 'solala-demo'
    message: dict[str, Any] = {'message_id': message_id, 'command': command}
    if args:
        message['args'] = args
    await ws.send_json(message)

    while True:
        response = await ws.receive(timeout=60)
        if response.type != aiohttp.WSMsgType.TEXT:
            raise RuntimeError(f'Matter WebSocket closed or failed: {response.type}')
        data = json.loads(response.data)
        if data.get('message_id') != message_id:
            continue  # Ignore asynchronous node events and server greetings.
        if data.get('message_type') == 'error':
            raise RuntimeError(f'Matter command failed: {data}')
        return data.get('result')


async def main() -> None:
    """
    Explore a Tapo P110M through a separate Matter controller server.

    Requires an already-running Matter Server with a WebSocket endpoint.
    The plug's LAN IP and Tapo account credentials are not used by Matter.

    Inspect commissioned Matter nodes or operate a selected plug
    """

    action = config.MATTER_ACTION  # 'status', 'commission', 'on', or 'off'
    if action not in ('status', 'commission', 'on', 'off'):
        raise ValueError(f'Invalid MATTER_ACTION: {action!r}')
    if action == 'commission' and not config.MATTER_PAIRING_CODE:
        raise ValueError('MATTER_PAIRING_CODE is required for commissioning')

    timeout = aiohttp.ClientTimeout(total=90)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.ws_connect(config.MATTER_SERVER_URL) as ws:
            greeting = await ws.receive_json(timeout=15)
            print(f'Server greeting: {json.dumps(greeting, indent=2, default=str)}')

            if action == 'commission':
                # Network-only commissioning: the plug is already on Wi-Fi.
                # Enable Matter pairing / multi-admin in the Tapo app first.
                result = await request(
                    ws, 'commission_with_code',
                    code=config.MATTER_PAIRING_CODE, network_only=True,
                )
                print(f'Commissioning result: {json.dumps(result, indent=2, default=str)}')
            elif action in ('on', 'off'):
                result = await request(
                    ws, 'device_command', node_id=config.MATTER_NODE_ID,
                    endpoint_id=config.MATTER_ENDPOINT_ID, cluster_id=6,
                    command_name='On' if action == 'on' else 'Off',
                    payload={},
                )
                print(f'Switch result: {result!r}')

            nodes = await request(ws, 'get_nodes')
            print(f'Commissioned nodes: {json.dumps(nodes, indent=2, default=str)}')
            print('Look for OnOff (cluster 6), ElectricalPowerMeasurement (144),')
            print('and ElectricalEnergyMeasurement (145) in the node attributes.')


if __name__ == '__main__':
    asyncio.run(main())
