import asyncio

from solala.register_bank import RegisterBank
from solala.utils.local_config_help import config
from solala.delegates.power_consumer.tesla_wall_connector.tesla_wall_connector import TeslaWallConnector


async def main() -> None:
    async with TeslaWallConnector(config.TESLA_WALL_CONNECTOR_ADDR) as device:
        register_bank: RegisterBank = await device.get_registers()
        for name, register in register_bank.items():
            value = await register.get()
            print(f'{name} =  {value!r}')


if __name__ == '__main__':
    asyncio.run(main())
