from dataclasses import dataclass
from datetime import datetime
from typing import List, Dict

import requests

from solala.power_pricer.power_pricer import PowerPricer, Price
from solala.utils.json import JSONDict, json_str, json_num, json_bool, json_dict

API = 'https://api.amber.com.au/v1'


@dataclass
class ChannelPair:
    general: JSONDict
    feed_in: JSONDict


class AmberPowerPricer(PowerPricer):

    def __init__(self, api_token: str, nmi: str):
        self._api_token: str = api_token
        self._nmi: str = nmi
        self._site: JSONDict = self._get_site()
        self._site_id: str = json_str(self._site['id'])

    @property
    def site_id(self) -> str:
        return self._site_id

    def close(self) -> None:
        # noting to do
        pass

    def get_price(self, forecasts: int) -> List[Price]:
        if forecasts < 0:
            raise ValueError('Forecasts must be non-negative')

        url = f'{API}/sites/{self._site_id}/prices/current'
        headers = {
            'accept': 'application/json',
            'Authorization': f'Bearer {self._api_token}'
        }
        params = {
            'previous': 0,
            'next': forecasts,
            'resolution': 5,
        }
        response = requests.get(url, headers=headers, params=params)
        if response.status_code != requests.codes.ok:
            raise IOError(f'error accessing Amber prices: {response}')

        # Parse the response
        parsed: Dict[datetime, ChannelPair] = {}
        response_json = response.json()
        for channel in response_json:
            start_time = _get_datetime(channel['startTime'])
            pair = parsed.get(start_time)
            if pair is None:
                pair = ChannelPair({}, {})
                parsed[start_time] = pair

            channel_type = channel['channelType']
            if channel_type == 'general':
                if len(pair.general) == 0:
                    pair.general = channel
                else:
                    raise IOError(f'duplicate general channel: {start_time}')
            elif channel_type == 'feedIn':
                if len(pair.feed_in) == 0:
                    pair.feed_in = channel
                else:
                    raise IOError(f'duplicate feed-in channel: {start_time}')

        result: List[Price] = [
            _make_price(start_time, pair)
            for start_time, pair in sorted(parsed.items())
        ]
        return result

    def _get_site(self) -> JSONDict:
        url = f'{API}/sites'
        headers = {
            'accept': 'application/json',
            'Authorization': f'Bearer {self._api_token}'
        }

        response = requests.get(url, headers=headers)
        data = response.json()

        # Search data for matching NMI
        for site in data:
            if site['nmi'] == self._nmi:
                return site

        raise ValueError(f'NMI not found in sites')


def _make_price(start_time: datetime, channel_pair: ChannelPair) -> Price:
    general: JSONDict = channel_pair.general
    feed_in: JSONDict = channel_pair.feed_in
    if len(general) == 0:
        raise IOError(f'no general channel found: {start_time}')
    if len(feed_in) == 0:
        raise IOError(f'no feed-in channel found: {start_time}')
    tariff_info: JSONDict = json_dict(general['tariffInformation'])

    return Price(
        start_time=start_time,
        end_time=_get_datetime(json_str(general['endTime'])),
        renewables=json_num(general['renewables']),
        buy_price=json_num(general['perKwh']),
        feed_in_price=-json_num(feed_in['perKwh']),
        tariff_period=json_str(tariff_info['period']),
        tariff_season=json_str(tariff_info['season']),
        tariff_demand_window=json_bool(tariff_info['demandWindow']),
    )


def _get_datetime(date: str) -> datetime:
    return datetime.fromisoformat(date).astimezone()
