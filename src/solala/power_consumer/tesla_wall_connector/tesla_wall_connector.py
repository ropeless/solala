from typing import Iterable, Tuple

import requests

from solala.power_consumer.power_consumer import PowerConsumer, ConsumerStatus
from solala.server_constants import LOGGER
from solala.utils.json import JSONDict, json_dict, json_num

NAME: str = 'Tesla Wall Charger'


class TeslaWallConnector(PowerConsumer):
    """
    Implementation of the CarCharger interface for Tesla Wall Connector.
    """

    def __init__(self, ip_address: str, mac_address: str = '') -> None:
        self._api = f'http://{ip_address}/api/1/'

        self._connection_status = {
            'status': 'Tesla Wall Connector connection',
            'host': ip_address,
        }
        if mac_address != '':
            self._connection_status['mac_address'] = mac_address

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

    def get_status(self) -> ConsumerStatus:
        data: JSONDict = self.get_vitals()
        return ConsumerStatus(
            voltage=json_num(data['voltageA_v']),
            current=json_num(data['currentA_a']),
        )

    def get_connection_status(self) -> JSONDict:
        return self._connection_status

    def close(self) -> None:
        # Nothing to do
        pass

    def get_vitals(self) -> JSONDict:
        url = self._api + 'vitals'
        response = requests.get(url)
        data: JSONDict = json_dict(response.json())
        return data
