import asyncio

from solala.utils.local_config_help import config
from solala.delegates.power_consumer.tesla_wall_connector.tesla_wall_connector import TeslaWallConnector


async def main() -> None:
    async with TeslaWallConnector(config.TESLA_WALL_CONNECTOR_ADDR) as device:
        for name, value in (await device.get_registers()).items():
            print(f'{name} =  {value!r}')


if __name__ == '__main__':
    asyncio.run(main())
