from dataclasses import dataclass
from datetime import datetime

from solala.utils.json_extras import JSONDict, to_json


@dataclass(frozen=True)
class Price:
    """
    Represents an immutable electricity price for a pricing interval.

    Attributes:
        start_time: Start of the pricing interval, including date, time and timezone.
        end_time: End of the pricing interval, including date, time and timezone.
        buy_price: Electricity purchase price, in cents per kWh.
        feed_in_price: Electricity feed-in price, in cents per kWh.
        renewables: Percentage of electricity generated from renewable sources.
        is_estimate: Whether the prices are estimates rather than actual prices.
        tariff_period: Optional tariff period classification, or an empty string
            if unavailable.
        tariff_season: Optional tariff season classification, or an empty string
            if unavailable.
        tariff_demand_window: Whether the interval falls within a tariff demand
            window.
    """

    start_time: datetime
    end_time: datetime

    buy_price: float
    feed_in_price: float
    renewables: float
    is_estimate: bool

    tariff_period: str = ''
    tariff_season: str = ''
    tariff_demand_window: bool = False

    def to_json(self, datetime_format: str, include_time: bool) -> JSONDict:
        """
        Convert the price to a JSON-compatible dictionary.

        Args:
            datetime_format: Format string used to represent datetime values.
            include_time: Whether to include the pricing interval's start and end
                times.

        Returns:
            A JSON-compatible dictionary. Empty string fields are excluded.
        """
        exclude_names = set() if include_time else {'start_time', 'end_time'}
        exclude_values = ('',)
        return to_json(
            self,
            datetime_format=datetime_format,
            exclude_names=exclude_names,
            exclude_values=exclude_values,
        )
