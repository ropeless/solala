import asyncio
from pprint import pprint

from solala.utils.local_config_help import config
from solala.delegates.power_pricer.amber_power_pricer.amber_power_pricer import AmberPowerPricer
from solala.delegates.power_pricer.power_pricer import Price


async def main() -> None:
    async with AmberPowerPricer(config.AMBER_API_TOKEN, config.NMI) as amber:
        price: Price = await amber.get_price()
        pprint(price)


if __name__ == '__main__':
    asyncio.run(main())
