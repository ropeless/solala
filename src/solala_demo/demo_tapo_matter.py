import asyncio
import json
from typing import Any

import aiohttp

from solala.utils.local_config_help import config


async def main() -> None:
    """
    Connect to Matter Server and display commissioned nodes.

    The P110M must already be commissioned through the Matter Server dashboard.
    """
    url = f'ws://{config.MATTER_SERVER_HOST}:{config.MATTER_SERVER_PORT}/ws'

    timeout = aiohttp.ClientTimeout(total=30)

    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.ws_connect(url) as ws:
            greeting = await ws.receive_json(timeout=15)
            if 'sdk_version' not in greeting:
                raise RuntimeError(f'Unexpected Matter Server greeting: {greeting!r}')
            print(f'Server: {greeting.get("sdk_version", "unknown")}')

            await ws.send_json({
                'message_id': 'get-nodes',
                'command': 'get_nodes',
            })

            while True:
                response = await ws.receive(timeout=30)
                if response.type != aiohttp.WSMsgType.TEXT:
                    raise RuntimeError(f'Matter WebSocket closed or failed: {response.type!r}')

                data: dict[str, Any] = json.loads(response.data)
                if data.get('message_id') != 'get-nodes':
                    continue
                if data.get('message_type') == 'error' or 'error_code' in data:
                    raise RuntimeError(f'Matter Server error: {data!r}')

                print(json.dumps(data.get('result'), indent=2, default=str))
                break


if __name__ == '__main__':
    asyncio.run(main())
