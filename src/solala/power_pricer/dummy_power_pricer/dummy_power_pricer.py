import random
from datetime import datetime, UTC, timedelta
from typing import List, Optional, Dict

from solala.power_pricer.power_pricer import PowerPricer, Price


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
    ):
        self.buy_price_min: float = buy_price_min
        self.buy_price_range: float = buy_price_max - buy_price_min
        self.feed_in_price_discount_min: float = feed_in_price_discount_min
        self.feed_in_price_discount_range: float = feed_in_price_discount_max - feed_in_price_discount_min
        self.cur_price_is_estate: bool = cur_price_is_estimate
        self.prices: List[Price] = []

    def get_connection_status(self) -> Dict[str, int | float | str]:
        return {
            'status': 'Dummy connection',
            'buy_price_min': self.buy_price_min,
            'buy_price_max': self.buy_price_min + self.buy_price_range,
            'feed_in_price_discount_min': self.feed_in_price_discount_min,
            'feed_in_price_discount_max': self.feed_in_price_discount_min + self.feed_in_price_discount_range,
            'cur_price_is_estimate': self.cur_price_is_estate,
        }

    def get_price(self) -> Price:
        now: datetime = datetime.now(UTC)
        start_time: datetime = now - timedelta(
            minutes=now.minute % 5,
            seconds=now.second,
            microseconds=now.microsecond
        )
        five_minutes: timedelta = timedelta(minutes=5)

        # remove historical prices
        while len(self.prices) > 0 and self.prices[0].end_time < now:
            self.prices.pop(0)

        # configure current price
        end_time: datetime = start_time + five_minutes
        if len(self.prices) == 0:
            buy_price = self._get_buy_price()
            feed_in_price = self._get_feed_in_price(buy_price)
            renewables = 59.1
            self.prices.append(
                Price(
                    buy_price=buy_price,
                    feed_in_price=feed_in_price,
                    renewables=renewables,
                    start_time=start_time,
                    end_time=end_time,
                    estimate=self.cur_price_is_estate,
                )
            )
        else:
            cur_price = self.prices[0]
            self.prices[0] = Price(
                buy_price=cur_price.buy_price,
                feed_in_price=cur_price.feed_in_price,
                renewables=cur_price.renewables,
                start_time=start_time,
                end_time=end_time,
                estimate=self.cur_price_is_estate,
            )

        return self.prices[0]

    def get_price_forecast(self, count: int) -> List[Price]:
        prices_per_30 = 30 // 5
        needed_prices: int = count * prices_per_30
        five_minutes: timedelta = timedelta(minutes=5)

        self.get_price()  # ensure at least one price cached
        prices = self.prices

        # append any required forecasts
        while len(prices) < needed_prices:
            prev_price = prices[-1]
            buy_price = self._get_buy_price(prev_price.buy_price)
            feed_in_price = self._get_feed_in_price(buy_price)
            renewables = (prev_price.renewables + 100 * random.random()) / 2
            prices.append(
                Price(
                    buy_price=buy_price,
                    feed_in_price=feed_in_price,
                    renewables=renewables,
                    start_time=prev_price.end_time,
                    end_time=prev_price.end_time + five_minutes,
                    estimate=True,
                )
            )

        return [_average_price(prices[i:i + prices_per_30]) for i in range(0, needed_prices, prices_per_30)]

    def close(self) -> None:
        # nothing to do
        pass

    def _get_buy_price(self, prev_buy_price: Optional[float] = None) -> float:
        price = self.buy_price_min + self.buy_price_range * random.random()
        if prev_buy_price is None:
            return price
        else:
            return (prev_buy_price * 3 + price) / 4  # Smooth the transition to the new price

    def _get_feed_in_price(self, buy_price: float) -> float:
        return buy_price - self.feed_in_price_discount_min - random.random() * self.feed_in_price_discount_range


def _average_price(prices: List[Price]) -> Price:
    return Price(
        buy_price=sum(price.buy_price for price in prices) / len(prices),
        feed_in_price=sum(price.feed_in_price for price in prices) / len(prices),
        renewables=sum(price.renewables for price in prices) / len(prices),
        start_time=prices[0].start_time,
        end_time=prices[-1].end_time,
        estimate=True,
    )
