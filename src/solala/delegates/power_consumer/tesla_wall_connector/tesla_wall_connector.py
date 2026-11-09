from typing import Tuple, List

from solala.delegates.power_consumer.power_consumer import PowerConsumer, ConsumerStatus
from solala.logger import LOGGER
from solala.utils.httpx_extras import async_get
from solala.utils.json import JSONDict, json_dict, json_num

NAME: str = 'Tesla Wall Charger'


class TeslaWallConnector(PowerConsumer):
    """
    Implementation of the CarCharger interface for Tesla Wall Connector.
    """

    def __init__(self, host: str, mac_address: str = '') -> None:
        self._api = f'http://{host}/api/1/'

        self._connection_status = {
            'connection': 'Tesla Wall Connector',
            'host': host,
        }
        if mac_address != '':
            self._connection_status['mac_address'] = mac_address

    async def get_status(self) -> ConsumerStatus:
        data: JSONDict = await self._get_vitals()
        return ConsumerStatus(
            voltage=json_num(data['voltageA_v']),
            current=json_num(data['currentA_a']),
        )

    def get_connection_status(self) -> JSONDict:
        return self._connection_status

    async def close(self) -> None:
        pass

    async def _get_vitals(self) -> JSONDict:
        url = self._api + 'vitals'
        response = await async_get(url)
        return json_dict(response.json())
