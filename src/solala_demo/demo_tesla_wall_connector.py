import asyncio

from solala.registers import RegisterBank
from solala.utils.local_config_help import config
from solala.delegates.power_consumer.tesla_wall_connector.tesla_wall_connector import TeslaWallConnector


async def main() -> None:
    async with TeslaWallConnector(config.TESLA_WALL_CONNECTOR_ADDR) as device:
        register: RegisterBank = await device.get_registers()
        async for name, value in register.items():
            print(f'{name} =  {value!r}')


if __name__ == '__main__':
    asyncio.run(main())
