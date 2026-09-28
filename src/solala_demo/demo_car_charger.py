import json

from local_config import TESLA_WALL_CONNECTOR_ADDR
from solala.car_charger.impl_tesla_wall_connector.tesla_wall_charger import TeslaWallCharger


def main() -> None:
    with TeslaWallCharger(TESLA_WALL_CONNECTOR_ADDR) as charger:
        # print(json.dumps(charger.get_vitals(), indent=4))
        print(json.dumps(charger.get_status().as_dict(), indent=4))


if __name__ == '__main__':
    main()
