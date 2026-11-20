import asyncio
import json

import httpx

from solala.delegates.power_consumer.tesla_wall_connector.tesla_wall_connector import TeslaWallConnector
from solala.register_bank import RegisterBank
from solala.utils.local_config_help import config


async def query_energy() -> None:
    # noinspection HttpUrlsUsage
    url = f'http://{config.TESLA_WALL_CONNECTOR_ADDR}/api/1/lifetime'

    async with httpx.AsyncClient() as client:
        response = await client.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()

    print(json.dumps(data, indent=2))
    print(f"Lifetime energy: {float(data['energy_wh']) / 1000:.3f} kWh")


async def main() -> None:
    async with TeslaWallConnector(config.TESLA_WALL_CONNECTOR_ADDR) as device:
        register_bank: RegisterBank = await device.get_registers()
        for name, register in register_bank.items():
            value = await register.get()
            print(f'{name} =  {value!r}')

    # await query_energy()


if __name__ == '__main__':
    asyncio.run(main())
