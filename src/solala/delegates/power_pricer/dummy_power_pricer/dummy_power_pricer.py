import random
from datetime import datetime, timedelta, date, time

from solala.constants import GUI_TIME_FORMAT
from solala.delegates.power_pricer.power_pricer import PowerPricer, Price
from solala.utils.datetime_extras import ensure_date, local_time_zone
from solala.utils.json_extras import JSONDict

_FIVE_MINUTES: timedelta = timedelta(minutes=5)

class DummyPowerPricer(PowerPricer):
    """
    A dummy power pricer for testing and demonstration purposes.
    Values are random.
    """

    def __init__(
            self,
            buy_price_min: float = 1,
            buy_price_max: float = 20,
            feed_in_price_discount_min: float = 2,
            feed_in_price_discount_max: float = 5,
            cur_price_is_estimate: bool = False,
            demand_window: tuple[time, time] | None = None,
    ):
        """
        If a demand window is provided, it will be interpreted as in the local time zone.
        """
        self._local_tz = local_time_zone()

        if demand_window is not None:
            demand_window = (
                demand_window[0].replace(tzinfo=self._local_tz),
                demand_window[1].replace(tzinfo=self._local_tz),
            )
            if not (demand_window[0] < demand_window[1]):
                raise ValueError('malformed demand window times')

        self.buy_price_min: float = buy_price_min
        self.buy_price_range: float = buy_price_max - buy_price_min
        self.feed_in_price_discount_min: float = feed_in_price_discount_min
        self.feed_in_price_discount_range: float = feed_in_price_discount_max - feed_in_price_discount_min
        self.cur_price_is_estate: bool = cur_price_is_estimate
        self.prices: list[Price] = []
        self.demand_window: tuple[time, time] | None = demand_window

    def get_connection_info(self) -> JSONDict:
        demand_window = (
            None if self.demand_window is None else
            [
                self.demand_window[0].strftime(GUI_TIME_FORMAT),
                self.demand_window[1].strftime(GUI_TIME_FORMAT),
            ]
        )
        return {
            'connection': self.__class__.__name__,
            'buy_price_min': self.buy_price_min,
            'buy_price_max': self.buy_price_min + self.buy_price_range,
            'feed_in_price_discount_min': self.feed_in_price_discount_min,
            'feed_in_price_discount_max': self.feed_in_price_discount_min + self.feed_in_price_discount_range,
            'cur_price_is_estimate': self.cur_price_is_estate,
            'demand_window': demand_window,
        }

    async def get_price(self) -> Price:
        now: datetime = datetime.now(self._local_tz)

        # Ensure prices are up to date
        if len(self.prices) == 0:
            self._set_first_price(now)
        while self.prices[-1].end_time <= now:
            self._append_price()
        while len(self.prices) > 0 and self.prices[0].end_time < now:
            self.prices.pop(0)

        return self.prices[0]

    async def get_price_forecast(self, count: int) -> list[Price]:
        prices_per_30 = 30 // 5
        needed_prices: int = count * prices_per_30

        await self.get_price()  # ensure at least one price cached
        prices = self.prices

        # Append any required forecasts
        while len(prices) < needed_prices:
            self._append_price()

        # Convert 5-minute forecasts to 30-minute forecasts
        return [_average_price(prices[i:i + prices_per_30]) for i in range(0, needed_prices, prices_per_30)]

    def _set_first_price(self, now: datetime) -> None:
        assert len(self.prices) == 0

        start_time: datetime = now - timedelta(
            minutes=now.minute % 5,
            seconds=now.second,
            microseconds=now.microsecond
        )
        end_time: datetime = start_time + _FIVE_MINUTES
        is_demand_window: bool = self._is_demand_window(start_time, end_time)
        buy_price = self._get_buy_price()
        feed_in_price = self._get_feed_in_price(buy_price)
        renewables = 100 * random.random()
        self.prices.append(
            Price(
                buy_price=buy_price,
                feed_in_price=feed_in_price,
                renewables=renewables,
                start_time=start_time,
                end_time=end_time,
                is_estimate=self.cur_price_is_estate,
                tariff_demand_window=is_demand_window,
            )
        )

    def _append_price(self) -> None:
        assert len(self.prices) > 0

        prev_price: Price = self.prices[-1]
        buy_price = self._get_buy_price(prev_price.buy_price)
        feed_in_price = self._get_feed_in_price(buy_price)
        renewables = (prev_price.renewables + 100 * random.random()) / 2
        start_time = prev_price.end_time
        end_time = prev_price.end_time + _FIVE_MINUTES
        is_demand_window: bool = self._is_demand_window(start_time, end_time)

        self.prices.append(
            Price(
                buy_price=buy_price,
                feed_in_price=feed_in_price,
                renewables=renewables,
                start_time=start_time,
                end_time=end_time,
                is_estimate=True,
                tariff_demand_window=is_demand_window,
            )
        )

    def _is_demand_window(self, start: datetime, end: datetime) -> bool:
        """
        Does the period between start and end overlap with the demand period.
        """
        if self.demand_window is None:
            return False
        day: date = ensure_date(start, self._local_tz)
        from_time = datetime.combine(day, self.demand_window[0])
        to_time = datetime.combine(day, self.demand_window[1])
        return start < to_time and from_time < end

    async def get_demand_window(self, day: date) -> tuple[datetime, datetime] | None:
        if self.demand_window is None:
            return None
        else:
            d: date = ensure_date(day, local_time_zone())
            return (
                datetime.combine(d, self.demand_window[0]),
                datetime.combine(d, self.demand_window[1]),
            )

    async def close(self) -> None:
        # nothing to do
        pass

    def _get_buy_price(self, prev_buy_price: float | None = None) -> float:
        price = self.buy_price_min + self.buy_price_range * random.random()
        if prev_buy_price is None:
            return price
        else:
            return (prev_buy_price * 3 + price) / 4  # Smooth the transition to the new price

    def _get_feed_in_price(self, buy_price: float) -> float:
        return buy_price - self.feed_in_price_discount_min - random.random() * self.feed_in_price_discount_range

def _average_price(prices: list[Price]) -> Price:
    return Price(
        buy_price=sum(price.buy_price for price in prices) / len(prices),
        feed_in_price=sum(price.feed_in_price for price in prices) / len(prices),
        renewables=sum(price.renewables for price in prices) / len(prices),
        start_time=prices[0].start_time,
        end_time=prices[-1].end_time,
        is_estimate=True,
    )
