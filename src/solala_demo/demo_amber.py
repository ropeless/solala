import asyncio
from pprint import pprint

from local_config import AMBER_API_TOKEN, NMI
from solala.delegates.power_pricer.amber_power_pricer.amber_power_pricer import AmberPowerPricer
from solala.delegates.power_pricer.power_pricer import Price


async def main() -> None:
    async with AmberPowerPricer(AMBER_API_TOKEN, NMI) as amber:
        price: Price = await amber.get_price()
        pprint(price)


if __name__ == '__main__':
    asyncio.run(main())
