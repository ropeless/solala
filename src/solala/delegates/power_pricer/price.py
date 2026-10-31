from dataclasses import dataclass
from datetime import datetime

from solala.utils.json import JSONDict, to_json


@dataclass(frozen=True)
class Price:
    buy_price: float  # c per kWh
    feed_in_price: float  # c per kWh
    renewables: float  # percentage
    start_time: datetime  # date + time + timezone
    end_time: datetime  # date + time + timezone
    is_estimate: bool  # whether the price is an estimate or not

    # Optional tariff information.
    tariff_period: str = ''
    tariff_season: str = ''
    tariff_demand_window: bool = False

    def to_json(self, datetime_format: str, include_time: bool) -> JSONDict:
        exclude_names = set() if include_time else {'start_time', 'end_time'}
        exclude_values = ('',)
        return to_json(
            self,
            datetime_format=datetime_format,
            exclude_names=exclude_names,
            exclude_values=exclude_values,
        )
