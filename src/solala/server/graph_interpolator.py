from datetime import date, datetime, timedelta
from collections.abc import Iterable, Sequence

import numpy as np
from scipy.interpolate import CubicSpline

from solala.database.measurement import Measurement
from solala.delegates.power_pricer.price import Price
from solala.delegates.solar_forecaster.solar_forecast import DailySolarForecast
from solala.utils.datetime_extras import local_time_zone, ensure_date, date_to_datetime


class GraphingInterpolator:
    """
    Interpolate measurements and forecasts onto a five-minute daily time grid.

    The grid contains 288 local-time timestamps. Power and energy properties
    produce graph-ready values; price properties use nearest-neighbour lookup.
    Missing input series produce empty lists, while some interpolation paths
    use NaN for values outside the available observations.
    """

    def __init__(
            self,
            day: date,
            measurements: Sequence[Measurement],
            price_forecast: Sequence[Price],
            solar_forecast: DailySolarForecast,
            demand_window: tuple[datetime, datetime] | None
    ) -> None:
        """
        Prepare the daily time grid and source timestamps.

        Args:
            day: Date to graph in the local time zone.
            measurements: Historical measurements used for actual graph series.
            price_forecast: Price intervals used for forecast price series.
            solar_forecast: Solar power and energy forecast intervals.
            demand_window: Optional start and end of the demand window.
        """
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

        self._demand_window = demand_window

    @property
    def demand_window(self) -> tuple[datetime, datetime] | None:
        """
        Return the optional demand-window time interval.
        """
        return self._demand_window

    @property
    def battery_charge(self) -> list[float]:
        values = [m.battery_charge for m in self._measurements]
        return self._interpolate_linear(self._ts_m, values)

    @property
    def accumulated_solar_energy(self) -> list[float]:
        return self._accumulated_daily_energy('accumulated_solar_energy')

    @property
    def accumulated_grid_energy_import(self) -> list[float]:
        return self._accumulated_daily_energy('accumulated_grid_energy_import')

    @property
    def accumulated_grid_energy_export(self) -> list[float]:
        return self._accumulated_daily_energy('accumulated_grid_energy_export')

    @property
    def accumulated_battery_energy_charge(self) -> list[float]:
        return self._accumulated_daily_energy('accumulated_battery_energy_charge')

    @property
    def accumulated_battery_energy_discharge(self) -> list[float]:
        return self._accumulated_daily_energy('accumulated_battery_energy_discharge')

    @property
    def average_solar_power(self) -> list[float]:
        return self._energy_to_power(
            self.accumulated_solar_energy,
            self._measurements[-1].accumulated_solar_energy,
        )

    @property
    def average_battery_power(self) -> list[float]:
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
    def average_grid_power(self) -> list[float]:
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
    def instantaneous_solar_power(self) -> list[float]:
        return self._instantaneous_power('solar_power')

    @property
    def instantaneous_grid_power(self) -> list[float]:
        return self._instantaneous_power('grid_power')

    @property
    def instantaneous_house_power(self) -> list[float]:
        return self._instantaneous_power('house_power')

    @property
    def instantaneous_battery_power(self) -> list[float]:
        return self._instantaneous_power('battery_power')

    @property
    def buy_price(self) -> list[float]:
        values = [m.buy_price for m in self._measurements]
        return self._interpolate_nearest(self._ts_m, values)

    @property
    def feed_in_price(self) -> list[float]:
        values = [m.feed_in_price for m in self._measurements]
        return self._interpolate_nearest(self._ts_m, values)

    @property
    def forecast_buy_price(self) -> list[float]:
        values = [price.buy_price for price in self._price_forecast]
        return self._interpolate_nearest(self._ts_f, values)

    @property
    def forecast_feed_in_price(self) -> list[float]:
        values = [price.feed_in_price for price in self._price_forecast]
        return self._interpolate_nearest(self._ts_f, values)

    @property
    def forecast_solar_power(self) -> list[float]:
        values = [forecast.power / 1000 for forecast in self._solar_forecast]
        return _ensure_non_negative(self._interpolate_cubic(self._ts_s, values, left=0, right=0))

    @property
    def forecast_accumulated_solar_energy(self) -> list[float]:
        values = _ensure_monotonic(_accumulate(forecast.energy / 1000 for forecast in self._solar_forecast))
        return _ensure_monotonic(_ensure_non_negative(self._interpolate_cubic(self._ts_s, values, left=0, right=None)))

    # ====================================================================
    #  Support functions
    # ====================================================================

    def _energy_to_power(self, data: list[float], boundary_value: float) -> list[float]:
        """
        Convert accumulated energy differences to average power in kW.

        Uses the final measurement as a boundary point when it falls after the
        last graph timestamp. The input list is modified by the conversion.

        Args:
            data: Accumulated energy values in kWh, coindexed with `timestamps`.
            boundary_value: Accumulated energy at the final measurement.

        Returns:
            Average power values in kW, coindexed with `timestamps`.
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

    def _accumulated_daily_energy(self, field: str) -> list[float]:
        """
        Interpolate an accumulated energy field and offset so the first value is zero.
        """
        values = [getattr(m, field) for m in self._measurements]
        return _ensure_monotonic(_zero(x / 1000 for x in self._interpolate_linear(self._ts_m, values)))

    def _instantaneous_power(self, field: str) -> list[float]:
        """
        Linearly interpolate a measured power field, converting watts to kW.
        """
        values = [getattr(m, field) for m in self._measurements]
        return [x / 1000 for x in self._interpolate_linear(self._ts_m, values)]

    def _interpolate_linear(
            self,
            timestamps: np.ndarray,
            values: list[float],
            left: float | None = np.nan,
            right: float | None = np.nan,
    ) -> list[float]:
        """
        Interpolate `values` onto the daily time grid using straight-line segments.
        """
        if len(values) == 0:
            return []
        y_values = np.array(values)
        interpolated_values = np.interp(self._ts, timestamps, y_values, left=left, right=right)
        return interpolated_values.tolist()

    def _interpolate_cubic(
            self,
            timestamps: np.ndarray,
            values: list[float],
            left: float | None = np.nan,
            right: float | None = np.nan,
    ) -> list[float]:
        """
        Interpolate `values` onto the daily time grid using a cubic spline.
        """
        if len(values) == 0:
            return []

        if left is not None or right is not None:
            ts = timestamps.tolist()
            if left is not None:
                values = [left] + values
                ts = [timestamps.item(0) - 0.1] + ts
            if right is not None:
                values += [right]
                ts += [timestamps.item(-1) + 0.1]
            timestamps = np.array(ts)
        y_values = np.array(values)

        # Extrapolate only if left or right is finite
        extrapolate: bool = (
                (left is not None and np.isfinite(left))
                or (right is not None and np.isfinite(right))
        )

        cs = CubicSpline(timestamps, y_values, bc_type='not-a-knot', extrapolate=extrapolate)
        interpolated_values = np.array(cs(self._ts), dtype=np.float64)
        return interpolated_values.tolist()

    def _interpolate_nearest(
            self,
            timestamps: np.ndarray,
            values: list[float],
            left: float | None = np.nan,
            right: float | None = np.nan,
    ) -> list[float]:
        """
        Interpolate `values` onto the daily time grid using the "nearest neighbour" algorithm.
        """
        if len(values) == 0:
            return []

        if left is not None or right is not None:
            ts = timestamps.tolist()
            if left is not None:
                values = [left] + values
                ts = [timestamps.item(0) - 0.1] + ts
            if right is not None:
                values += [right]
                ts += [timestamps.item(-1) + 0.1]
            timestamps = np.array(ts)
        y_values = np.array(values)

        indices = np.searchsorted(timestamps, self._ts)
        indices = np.clip(indices, 0, len(timestamps) - 1)
        left = indices - 1
        right = indices
        n = np.where(
            np.abs(self._ts - timestamps[left]) <= np.abs(timestamps[right] - self._ts),
            left,
            right,
        )

        interpolated_values = y_values[n]
        return interpolated_values.tolist()


def _ensure_monotonic(data: Iterable[float]) -> list[float]:
    """
    Replace decreasing values with the greatest value seen so far.
    """
    m = float('-inf')
    result: list[float] = []
    for x in data:
        m = max(x, m)
        result.append(m)
    return result


def _ensure_non_negative(data: Iterable[float]) -> list[float]:
    """
    Clamp negative values to zero.
    """
    return [
        max(0, x)
        for x in data
    ]


def _zero(data: Iterable[float]) -> list[float]:
    """
    Subtract the first non-NaN value, preserving leading NaNs.
    """
    it = iter(data)
    result: list[float] = []
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


def _accumulate(data: Iterable[float]) -> list[float]:
    """
    Return running totals of the supplied values.
    """
    result: list[float] = []
    acc = 0
    for x in data:
        acc += x
        result.append(acc)
    return result


def _diff(data: list[float], times: Sequence[datetime]) -> list[float]:
    """
    Convert successive energy differences to hourly rates in place.

    The last output value is NaN because no following timestamp is available.
    """
    end = len(data) - 1
    for i in range(end):
        seconds = (times[i + 1].timestamp() - times[i].timestamp())
        data[i] = (data[i + 1] - data[i]) / seconds * 3600
    data[end] = np.nan
    return data
