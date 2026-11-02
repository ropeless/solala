from datetime import date, datetime, timedelta
from typing import Sequence, List, Iterable, Optional

import numpy as np

from solala.database.measurement import Measurement
from solala.delegates.power_pricer.price import Price
from solala.delegates.solar_forecaster.solar_forecast import DailySolarForecast
from solala.utils.datetime_extras import local_time_zone, ensure_date, date_to_datetime


class GraphingInterpolator:
    """
    Interpolates measurements data to specific 5-minute timepoints for graphing.
    """

    def __init__(
            self,
            day: date,
            measurements: Sequence[Measurement],
            price_forecast: Sequence[Price],
            solar_forecast: DailySolarForecast,
    ):
        tz = local_time_zone()
        day = ensure_date(day, tz)
        day_as_datetime: datetime = date_to_datetime(day, tz)

        self.day: date = day
        self.timestamps: Sequence[datetime] = [
            day_as_datetime + timedelta(hours=hour, minutes=minute)
            for hour in range(24)
            for minute in range(0, 60, 5)
        ]
        self._measurements: Sequence[Measurement] = measurements
        self._price_forecast: Sequence[Price] = price_forecast
        self._solar_forecast: DailySolarForecast = solar_forecast
        self._ts = np.array([dt.timestamp() for dt in self.timestamps])
        self._ts_m = np.array([measurement.timestamp.timestamp() for measurement in measurements])
        self._ts_f = np.array([price.start_time.timestamp() for price in price_forecast])
        self._ts_s = np.array([forecast.start_time.timestamp() for forecast in solar_forecast])

    @property
    def battery_charge(self) -> List[float]:
        return self._interpolated_measurement_linear('battery_charge')

    @property
    def accumulated_solar_energy(self) -> List[float]:
        return self._accumulated_daily_energy('accumulated_solar_energy')

    @property
    def accumulated_grid_energy_import(self) -> List[float]:
        return self._accumulated_daily_energy('accumulated_grid_energy_import')

    @property
    def accumulated_grid_energy_export(self) -> List[float]:
        return self._accumulated_daily_energy('accumulated_grid_energy_export')

    @property
    def accumulated_battery_energy_charge(self) -> List[float]:
        return self._accumulated_daily_energy('accumulated_battery_energy_charge')

    @property
    def accumulated_battery_energy_discharge(self) -> List[float]:
        return self._accumulated_daily_energy('accumulated_battery_energy_discharge')

    @property
    def average_solar_power(self) -> List[float]:
        return self._energy_to_power(
            self.accumulated_solar_energy,
            self._measurements[-1].accumulated_solar_energy,
        )

    @property
    def average_battery_power(self) -> List[float]:
        data = [
            x - y
            for x, y in zip(
                self.accumulated_battery_energy_charge,
                self.accumulated_battery_energy_discharge,
            )
        ]
        last = self._measurements[-1]
        boundary_value = last.accumulated_battery_energy_charge - last.accumulated_battery_energy_discharge
        return self._energy_to_power(data, boundary_value)

    @property
    def average_grid_power(self) -> List[float]:
        data = [
            x - y
            for x, y in zip(
                self.accumulated_grid_energy_import,
                self.accumulated_grid_energy_export,
            )
        ]
        last = self._measurements[-1]
        boundary_value = last.accumulated_grid_energy_import - last.accumulated_grid_energy_export
        return self._energy_to_power(data, boundary_value)

    @property
    def instantaneous_solar_power(self) -> List[float]:
        return self._instantaneous_power('solar_power')

    @property
    def instantaneous_grid_power(self) -> List[float]:
        return self._instantaneous_power('grid_power')

    @property
    def instantaneous_house_power(self) -> List[float]:
        return self._instantaneous_power('house_power')

    @property
    def instantaneous_battery_power(self) -> List[float]:
        return self._instantaneous_power('battery_power')

    @property
    def buy_price(self) -> List[float]:
        return self._interpolated_measurement_nearest('buy_price')

    @property
    def feed_in_price(self) -> List[float]:
        return self._interpolated_measurement_nearest('feed_in_price')

    @property
    def forecast_buy_price(self) -> List[float]:
        values = [price.buy_price for price in self._price_forecast]
        return self._interpolate_nearest(self._ts_f, values)

    @property
    def forecast_feed_in_price(self) -> List[float]:
        values = [price.feed_in_price for price in self._price_forecast]
        return self._interpolate_nearest(self._ts_f, values)

    @property
    def forecast_solar_power(self) -> List[float]:
        values = [forecast.power for forecast in self._solar_forecast]
        return self._interpolate_linear(self._ts_s, values, left=0, right=0)

    @property
    def forecast_accumulated_solar_energy(self) -> List[float]:
        values = list(_accumulate(forecast.energy for forecast in self._solar_forecast))
        return self._interpolate_linear(self._ts_s, values, left=0, right=None)

    # ====================================================================
    #  Support functions
    # ====================================================================

    def _energy_to_power(self, data, boundary_value: float) -> List[float]:
        """
        Convert accumulated energy to average power for each period.
        Args:
            data: the accumulated energy values, co-indexed with self.timestamps.
            boundary_value: the energy value of self._measurements[-1]

        Returns:
            power values, co-indexed with self.timestamps.
        """
        times = self.timestamps
        boundary_time = self._measurements[-1].timestamp

        if boundary_time > times[-1]:
            # Add a boundary point to give the last power value.
            times = list(times) + [boundary_time]
            data += [boundary_value]
            data = _diff(data, times)
            data.pop()
        else:
            data = _diff(data, times)

        return data

    def _accumulated_daily_energy(self, field: str) -> List[float]:
        return _ensure_monotonic(_zero(x / 1000 for x in self._interpolated_measurement_linear(field)))

    def _instantaneous_power(self, field: str) -> List[float]:
        return [x / 1000 for x in self._interpolated_measurement_linear(field)]

    def _interpolated_measurement_linear(self, field: str) -> List[float]:
        values = [getattr(m, field) for m in self._measurements]
        return self._interpolate_linear(self._ts_m, values)

    def _interpolated_measurement_nearest(self, field: str) -> List[float]:
        values = [getattr(m, field) for m in self._measurements]
        return self._interpolate_nearest(self._ts_m, values)

    def _interpolate_linear(
            self,
            timestamps: np.ndarray,
            values: List[float],
            left: Optional[float] = np.nan,
            right: Optional[float] = np.nan,
    ) -> List[float]:
        y_values = np.array(values)
        interpolated_values = np.interp(self._ts, timestamps, y_values, left=left, right=right)
        return interpolated_values.tolist()

    def _interpolate_nearest(
            self,
            timestamps: np.ndarray,
            values: List[float],
            left: Optional[float] = np.nan,
            right: Optional[float] = np.nan,
    ) -> List[float]:
        if left is not None:
            values = [left] + values
        if right is not None:
            values += [right]
        y_values = np.array(values)

        if left is not None or right is not None:
            ts = timestamps.tolist()
            if left is not None:
                ts = [timestamps.item(0) - 0.1] + ts
            if right is not None:
                ts += [timestamps.item(-1) + 0.1]
            timestamps = np.array(ts)

        indices = np.searchsorted(timestamps, self._ts)
        left = np.clip(indices - 1, 0, len(timestamps) - 1)
        right = np.clip(indices, 0, len(timestamps) - 1)
        n = np.where(
            np.abs(self._ts - timestamps[left]) <= np.abs(timestamps[right] - self._ts),
            left,
            right,
        )

        interpolated_values = y_values[n]
        return interpolated_values.tolist()


def _ensure_monotonic(data: Iterable[float]) -> List[float]:
    m = float('-inf')
    result: List[float] = []
    for x in data:
        m = max(x, m)
        result.append(m)
    return result


def _zero(data: Iterable[float]) -> List[float]:
    it = iter(data)
    result: List[float] = []
    try:
        first = next(it)
    except StopIteration:
        return result
    while np.isnan(first):
        result.append(first)
        try:
            first = next(it)
        except StopIteration:
            return result
    result.append(0)
    result.extend(val - first for val in it)
    return result


def _accumulate(data: Iterable[float]) -> List[float]:
    result: List[float] = []
    acc = 0
    for x in data:
        acc += x
        result.append(acc)
    return result


def _diff(data: List[float], times: Sequence[datetime]) -> List[float]:
    end = len(data) - 1
    for i in range(end):
        seconds = (times[i + 1].timestamp() - times[i].timestamp())
        data[i] = (data[i + 1] - data[i]) / seconds * 3600
    data[end] = np.nan
    return data
