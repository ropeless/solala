import random
from datetime import datetime, UTC, timedelta
from typing import List

from solala.power_pricer.power_pricer import PowerPricer, Price


class DummyPowerPricer(PowerPricer):
    """
    A dummy power pricer for testing and demonstration purposes.
    Values are random.
    """

    def __init__(self):
        self.buy_price_max: float = 20
        self.cur_price_is_estate: bool = True
        self.prices: List[Price] = []

    def get_price(self, forecasts: int) -> List[Price]:
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
            buy_price = self.buy_price_max * random.random()
            feed_in_price = buy_price - 2 - random.random()
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

        # append any required forecasts
        while len(self.prices) <= forecasts:
            prev_price = self.prices[-1]
            buy_price = (prev_price.buy_price + self.buy_price_max * random.random()) / 2
            feed_in_price = buy_price - 2 - random.random()
            renewables = (prev_price.renewables + 100 * random.random()) / 2
            self.prices.append(
                Price(
                    buy_price=buy_price,
                    feed_in_price=feed_in_price,
                    renewables=renewables,
                    start_time=prev_price.end_time,
                    end_time=prev_price.end_time + five_minutes,
                    estimate=True,
                )
            )

        return self.prices[:forecasts + 1]

    def close(self) -> None:
        # nothing to do
        pass
