''"Explore a Tapo P110M through a separate Matter controller server.

Requires an already-running Matter Server with a WebSocket endpoint.
The plug's LAN IP and Tapo account credentials are not used by Matter.
''"

import argparse
import asyncio
import json
from typing import Any

import aiohttp

from solala.utils.local_config_help import config


async def request(ws: aiohttp.ClientWebSocketResponse, command: str, **args: Any) -> Any:
    '''\n    Send a Matter Server command and wait for its matching response.\n    '''
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
    '''\n    Inspect commissioned Matter nodes or operate a selected plug.\n    '''
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--server', default=config.MATTER_SERVER_URL)
    parser.add_argument('--action', choices=('status', 'on', 'off', 'commission'), default='status')
    parser.add_argument('--node', type=int, help='Matter node ID for on/off')
    parser.add_argument('--endpoint', type=int, default=1, help='OnOff endpoint (default 1)')
    args = parser.parse_args()

    if args.action in ('on', 'off') and args.node is None:
        parser.error('--node is required for on/off')
    if args.action == 'commission' and not config.MATTER_PAIRING_CODE:
        parser.error('Set MATTER_PAIRING_CODE to the pairing code from the Tapo app')

    timeout = aiohttp.ClientTimeout(total=90)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.ws_connect(args.server) as ws:
            greeting = await ws.receive_json(timeout=15)
            print(f'Server greeting: {json.dumps(greeting, indent=2, default=str)}')

            if args.action == 'commission':
                # Network-only commissioning: the plug is already on Wi-Fi.
                # Enable Matter pairing / multi-admin in the Tapo app first.
                result = await request(
                    ws, 'commission_with_code',
                    code=config.MATTER_PAIRING_CODE, network_only=True,
                )
                print(f'Commissioning result: {json.dumps(result, indent=2, default=str)}')
            elif args.action in ('on', 'off'):
                result = await request(
                    ws, 'device_command', node_id=args.node,
                    endpoint_id=args.endpoint, cluster_id=6,
                    command_name='On' if args.action == 'on' else 'Off',
                    payload={},
                )
                print(f'Switch result: {result!r}')

            nodes = await request(ws, 'get_nodes')
            print(f'Commissioned nodes: {json.dumps(nodes, indent=2, default=str)}')
            print('Look for OnOff (cluster 6), ElectricalPowerMeasurement (144),')
            print('and ElectricalEnergyMeasurement (145) in the node attributes.')


if __name__ == '__main__':
    asyncio.run(main())
