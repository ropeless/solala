from typing import Tuple, List

import httpx

from solala.logger import LOGGER
from solala.power_consumer.power_consumer import PowerConsumer, ConsumerStatus
from solala.utils.json import JSONDict, json_dict, json_num

NAME: str = 'Tesla Wall Charger'


class TeslaWallConnector(PowerConsumer):
    """
    Implementation of the CarCharger interface for Tesla Wall Connector.
    """

    def __init__(self, host: str, mac_address: str = '') -> None:
        self._api = f'http://{host}/api/1/'
        self._client = httpx.AsyncClient()

        self._connection_status = {
            'connection': 'Tesla Wall Connector',
            'host': host,
        }
        if mac_address != '':
            self._connection_status['mac_address'] = mac_address

    async def get_registers(self) -> List[Tuple[str, int | float | str | bool]]:
        """
        Get the values of all known registers.
        """
        data: JSONDict = await self._get_vitals()
        result: List[Tuple[str, int | float | str | bool]] = []
        for key, value in data.items():
            if not isinstance(value, (int, float, str, bool)):
                LOGGER.info(f'[{NAME}] unexpected vitals entry: {key} = {value!r}')
                continue
            result.append((key, value))
        return result

    async def get_status(self) -> ConsumerStatus:
        data: JSONDict = await self._get_vitals()
        return ConsumerStatus(
            voltage=json_num(data['voltageA_v']),
            current=json_num(data['currentA_a']),
        )

    def get_connection_status(self) -> JSONDict:
        return self._connection_status

    async def close(self) -> None:
        await self._client.aclose()

    async def _get_vitals(self) -> JSONDict:
        url = self._api + 'vitals'
        response = await self._client.get(url)
        return json_dict(response.json())
