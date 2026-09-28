from typing import Iterable, Tuple

import requests

from solala.car_charger.wall_charger import CarCharger, ChargerStatus
from solala.utils.json import JSONDict, json_dict, json_num
from solala.server_constants import LOGGER

NAME: str = 'Tesla Wall Charger'


class TeslaWallConnector(CarCharger):
    """
    Implementation of the CarCharger interface for Tesla Wall Connector.
    """

    def __init__(self, ip_address: str) -> None:
        self._api = f'http://{ip_address}/api/1/'

    def get_registers(self) -> Iterable[Tuple[str, int | float | str | bool]]:
        """
        Get the values of all known registers.
        """
        data: JSONDict = self.get_vitals()
        for key, value in data.items():
            if not isinstance(value, (int, float, str, bool)):
                LOGGER.info(f'[{NAME}] unexpected vitals entry: {key} = {value!r}')
                continue
            yield key, value

    def get_status(self) -> ChargerStatus:
        data: JSONDict = self.get_vitals()
        return ChargerStatus(
            voltage=json_num(data['voltageA_v']),
            current=json_num(data['currentA_a']),
        )

    def close(self) -> None:
        # Nothing to do
        pass

    def get_vitals(self) -> JSONDict:
        url = self._api + 'vitals'
        response = requests.get(url)
        data: JSONDict = json_dict(response.json())
        return data
