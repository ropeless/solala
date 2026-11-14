from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, date
from typing import Literal

import requests

from solala.delegates.power_pricer.power_pricer import PowerPricer, Price
from solala.utils.httpx_extras import async_get
from solala.utils.json_extras import JSONDict, json_str, json_num, json_bool, json_dict

API = 'https://api.amber.com.au/v1'


@dataclass
class _ChannelPair:
    general: JSONDict
    feed_in: JSONDict


type _PriceExtract = Callable[[JSONDict], float]


class AmberPowerPricer(PowerPricer):

    def __init__(self, api_token: str, nmi: str):
        self._api_token: str = api_token
        self._nmi: str = nmi
        self._site: JSONDict = self._get_site()
        self._site_id: str = json_str(self._site['id'])

    @property
    def nmi(self) -> str:
        return self._nmi

    @property
    def site_id(self) -> str:
        return self._site_id

    def get_connection_info(self) -> JSONDict:
        return {
            'connection': 'Amber',
            'nmi': self._nmi,
            'site': self._site_id,
        }

    async def close(self) -> None:
        pass

    async def get_price(self) -> Price:
        response = await self._get(5, 0)
        return _parse_response(response, _get_perKwh)[0]

    async def get_price_forecast(self, count: int) -> list[Price]:
        if count < 1:
            raise ValueError('Count must be positive')
        response = await self._get(30, count - 1)
        return _parse_response(response, _get_predicted)

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

    async def get_demand_window(self, day: date) -> tuple[datetime, datetime] | None:
        day_str: str = f'{day.year:04d}-{day.month:02d}-{day.day:02d}'

        url = f'{API}/sites/{self._site_id}/prices'
        headers = {
            'accept': 'application/json',
            'Authorization': f'Bearer {self._api_token}'
        }
        params = {
            'startDate': day_str,
            'endDate': day_str,
            'resolution': '30',
        }
        response = await async_get(url, headers=headers, params=params)
        if response.status_code != requests.codes.ok:
            raise IOError(f'error accessing Amber prices: {response}')

        prices: list[Price] = [
            price for price in _parse_response(response.json(), _get_no_price)
            if price.tariff_demand_window
        ]
        if len(prices) == 0:
            return None
        else:
            return prices[0].start_time, prices[-1].end_time

    async def _get(self, resolution: Literal[5, 30], forecasts: int) -> JSONDict:
        url = f'{API}/sites/{self._site_id}/prices/current'
        headers = {
            'accept': 'application/json',
            'Authorization': f'Bearer {self._api_token}'
        }
        params = {
            'previous': 0,
            'next': forecasts,
            'resolution': resolution,
        }

        response = await async_get(url, headers=headers, params=params)
        if response.status_code != requests.codes.ok:
            raise IOError(f'error accessing Amber prices: {response}')
        return response.json()


def _parse_response(response_json: Sequence[JSONDict], price_f: _PriceExtract) -> list[Price]:
    # Parse the response
    parsed: dict[datetime, _ChannelPair] = {}
    for channel in response_json:
        start_time = _get_datetime(json_str(channel['startTime']))
        pair = parsed.get(start_time)
        if pair is None:
            pair = _ChannelPair({}, {})
            parsed[start_time] = pair

        channel_type: str = json_str(channel['channelType'])
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

    result: list[Price] = [
        _make_price(start_time, pair, price_f)
        for start_time, pair in sorted(parsed.items())
    ]
    return result


def _make_price(start_time: datetime, channel_pair: _ChannelPair, price_f: _PriceExtract) -> Price:
    general: JSONDict = channel_pair.general
    feed_in: JSONDict = channel_pair.feed_in
    if len(general) == 0:
        raise IOError(f'no general channel found: {start_time}')
    if len(feed_in) == 0:
        raise IOError(f'no feed-in channel found: {start_time}')
    tariff_info: JSONDict = json_dict(general['tariffInformation'])

    estimate: bool = True if 'estimate' not in general else json_bool(general['estimate'])

    renewables: float = json_num(general['renewables'])
    renewables = max(0.0, min(renewables, 100.0))  # clamp renewables to 0-100 due to API limitations

    return Price(
        start_time=start_time,
        end_time=_get_datetime(json_str(general['endTime'])),
        renewables=renewables,
        buy_price=price_f(general),
        feed_in_price=-price_f(feed_in),
        is_estimate=estimate,
        tariff_period=json_str(tariff_info['period']),
        tariff_season=json_str(tariff_info['season']),
        tariff_demand_window=json_bool(tariff_info['demandWindow']),
    )


def _get_no_price(_: JSONDict) -> float:
    return 0.0


def _get_perKwh(data: JSONDict) -> float:
    return json_num(data['perKwh'])


def _get_predicted(data: JSONDict) -> float:
    try:
        return json_num(json_dict(data['advancedPrice'])['predicted'])
    except (KeyError, ValueError, TypeError):
        return _get_perKwh(data)


def _get_datetime(date_str: str) -> datetime:
    return datetime.fromisoformat(date_str).astimezone()
