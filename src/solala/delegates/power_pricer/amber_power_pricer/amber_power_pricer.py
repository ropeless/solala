from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, date
from typing import Literal

import httpx
import requests

from solala.delegates.power_pricer.power_pricer import PowerPricer, Price
from solala.utils.json_extras import JSONDict, json_str, json_num, json_bool, json_dict

API = 'https://api.amber.com.au/v1'


@dataclass
class _ChannelPair:
    general: JSONDict
    feed_in: JSONDict


type _PriceExtract = Callable[[JSONDict], float]


class AmberPowerPricer(PowerPricer):
    """
    Retrieves electricity prices and tariff information from the Amber API.
    """

    def __init__(self, api_token: str, nmi: str) -> None:
        """
        Initialise the pricer for an Amber electricity site.

        Args:
            api_token: Amber API authentication token (secret information).
            nmi: National Metering Identifier of the site to retrieve.
        """
        self._client = httpx.AsyncClient()
        self._api_token: str = api_token
        self._nmi: str = nmi
        self._site: JSONDict = self._get_site()
        self._site_id: str = json_str(self._site['id'])

    @property
    def nmi(self) -> str:
        """
        Get the National Metering Identifier of the configured site.
        """
        return self._nmi

    @property
    def site_id(self) -> str:
        """
        Get the Amber identifier of the configured site, for the configured NMI.
        """
        return self._site_id

    def get_connection_info(self) -> JSONDict:
        return {
            'connection': 'Amber',
            'nmi': self._nmi,
            'site': self._site_id,
        }

    async def close(self) -> None:
        await self._client.aclose()

    async def get_price(self) -> Price:
        response = await self._get(5, 0)
        return _parse_response(response, _get_perKwh)[0]

    async def get_price_forecast(self, count: int) -> list[Price]:
        if count < 1:
            raise ValueError('Count must be positive')
        response = await self._get(30, count - 1)
        return _parse_response(response, _get_predicted)

    def _get_site(self) -> JSONDict:
        """
        Retrieve the Amber site matching the configured NMI.

        Returns:
            The matching site information.

        Raises:
            ValueError: If no site matches the configured NMI.
        """
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

        raise ValueError(f'NMI not found in sites: {self._nmi!r}')

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
        response = await self._client.get(url, headers=headers, params=params)
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
        """
        Retrieve current and forecast prices from the Amber API.

        Args:
            resolution: Pricing interval in minutes (5 or 30).
            forecasts: Number of forecast intervals to request after the current
                interval.

        Returns:
            The API response containing the price channels.

        Raises:
            IOError: If the API request fails.
        """
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

        response = await self._client.get(url, headers=headers, params=params)
        if response.status_code != requests.codes.ok:
            raise IOError(f'error accessing Amber prices: {response}')
        return response.json()


def _parse_response(response_json: Sequence[JSONDict], price_f: _PriceExtract) -> list[Price]:
    """
    Parse Amber price channels into chronologically ordered prices.

    Channels are paired by their start time. Each interval must contain one
    general channel and one feed-in channel.

    Args:
        response_json: Price channel records returned by the Amber API.
        price_f: Function used to extract a price from a channel.

    Returns:
        Prices ordered by interval start time.

    Raises:
        IOError: If an interval contains duplicate channels or is missing either
            channel type.
    """
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
    """
    Create a Price from a pair of contemporary Amber price channels.

    Args:
        start_time: Start of the pricing interval.
        channel_pair: General and feed-in channel data for the interval.
        price_f: Function used to extract a price from a channel.

    Returns:
        The price for the interval, including tariff information.

    Raises:
        IOError: If either channel is missing.
    """
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
    """
    Return zero when a price value is not required.
    """
    return 0.0


def _get_perKwh(data: JSONDict) -> float:
    """
    Extract the per-kWh price from an Amber channel.

    Args:
        data: Amber price channel data.

    Returns:
        The per-kWh price.
    """
    return json_num(data['perKwh'])


def _get_predicted(data: JSONDict) -> float:
    """
    Extract the predicted price from an Amber channel when available.

    Falls back to the per-kWh price if the advanced prediction is unavailable.

    Args:
        data: Amber price channel data.

    Returns:
        The predicted or fallback per-kWh price.
    """
    try:
        return json_num(json_dict(data['advancedPrice'])['predicted'])
    except (KeyError, ValueError, TypeError):
        return _get_perKwh(data)


def _get_datetime(date_str: str) -> datetime:
    """
    Parse an ISO-formatted datetime and convert it to the local timezone.

    Args:
        date_str: ISO-formatted datetime string.

    Returns:
        The parsed datetime in the local timezone.
    """
    return datetime.fromisoformat(date_str).astimezone()
