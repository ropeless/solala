from pprint import pprint

from local_config import AMBER_API_TOKEN, NMI
from solala.power_pricer.impl_amber.amber_power_pricer import AmberPowerPricer


def main() -> None:
    amber = AmberPowerPricer(AMBER_API_TOKEN, NMI)
    price = amber.get_price(forecasts=1)
    pprint(price)


if __name__ == '__main__':
    main()
