from pprint import pprint

from local_config import AMBER_API_TOKEN, NMI
from solala.power_pricer.impl_amber.amber_power_pricer import Amber


def main() -> None:
    amber = Amber(AMBER_API_TOKEN, NMI)
    price = amber.get_price()
    pprint(price)


if __name__ == '__main__':
    main()
