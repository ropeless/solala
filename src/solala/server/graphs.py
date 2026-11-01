from datetime import datetime, date, timedelta
from typing import Dict, Sequence, List, Iterable

import numpy as np
from nicegui import ui
from nicegui.elements.echart import EChart
from scipy.interpolate import CubicSpline

from solala.constants import KILOWATTS, GUI_TIME_FORMAT, KILOWATT_HOURS
from solala.database.measurement import Measurement
from solala.utils.datetime_extras import ensure_date, date_to_datetime, local_time_zone
from solala.utils.json import JSONDict


def _rgba(colour: str, alpha: float = 0.1) -> str:
    colour = colour.lstrip('#')
    r, g, b = (int(colour[i:i + 2], 16) for i in (0, 2, 4))
    return f'rgba({r}, {g}, {b}, {alpha})'


def _create_series(name: str, data: List[float], colour: str) -> JSONDict:
    return {
        'name': name,
        'type': 'line',
        'data': data,
        'smooth': 0.25,
        'showSymbol': False,
        'color': colour,
        'lineStyle': {
            'width': 2.5,
            'color': colour,
        },
        'areaStyle': {
            'color': _rgba(colour, 0.10),
        },
    }


def _graph_tooltip(units: str) -> JSONDict:
    return {
        'trigger': 'axis',
        ':formatter': """(params) => {
            let result = params[0].axisValueLabel;

            params.forEach(item => {
                result += '<br/>' +
                    item.marker +
                    item.seriesName + ': ' +
                    Number(item.value).toFixed(2) + '""" + units + """';
            });

            return result;
        }"""
    }


def _xaxis(timestamps: Sequence[datetime]) -> JSONDict:
    timestamps = [timestamp.strftime(GUI_TIME_FORMAT) for timestamp in timestamps]
    return {
        'type': 'category',
        'boundaryGap': False,
        'data': timestamps,
        'axisLine': {
            'lineStyle': {'color': '#888'}
        },
        'axisTick': {'show': False},
        'axisLabel': {
            'color': '#888',
            'fontSize': 11
        }
    }


def _yaxis(name: str, units: str) -> JSONDict:
    return {
        'type': 'value',
        'name': f'{name} ({units.strip()})',
        'nameTextStyle': {'color': '#888'},
        'axisLabel': {
            'color': '#888',
            'fontSize': 11
        },
        'splitLine': {
            'lineStyle': {
                'color': '#888',
                'opacity': 0.2,
                'type': 'dashed'
            }
        }
    }


def _ensure_monotonic(data: Iterable[float]) -> List[float]:
    m = float('-inf')
    result: List[float] = []
    for x in data:
        m = max(x, m)
        result.append(m)
    return result


def _zero(data: Iterable[float]) -> List[float]:
    it = iter(data)
    first = next(it)
    result: List[float] = []
    while np.isnan(first):
        result.append(first)
        first = next(it)
    result.append(0)
    result.extend(val - first for val in it)
    return result


def _diff(data: Iterable[float]) -> List[float]:
    it = iter(data)
    result: List[float] = []
    prev: float = next(it)
    while np.isnan(prev):
        result.append(prev)
        prev = next(it)
    result.append(0)
    for val in it:
        result.append(val - prev)
        prev = val
    return result


def _daily_timestamps(day: date) -> Sequence[datetime]:
    day = date_to_datetime(day)
    return [
        day + timedelta(hours=hour, minutes=minute)
        for hour in range(24)
        for minute in range(0, 60, 5)
    ]


class DailyInterpolator:
    def __init__(self, measurements: Sequence[Measurement]):
        self._measurements = measurements
        self.day = ensure_date(measurements[0].timestamp, local_time_zone())
        self.timestamps: Sequence[datetime] = _daily_timestamps(self.day)
        self.ts_np = np.array([dt.timestamp() for dt in self.timestamps])
        self.ts_m = np.array([measurement.timestamp.timestamp() for measurement in measurements])
        self.earliest: float = self.ts_m.min()
        self.latest: float = self.ts_m.max()
        self.missing: List[int] = []

        for i in range(len(self.timestamps)):
            if self.ts_np[i] < self.earliest:
                self.missing.append(i)
            else:
                break
        for i in range(len(self.timestamps) - 1, -1, -1):
            if self.ts_np[i] > self.latest:
                self.missing.append(i)
            else:
                break

    def __call__(self, field: str) -> List[float]:
        values = [getattr(m, field) for m in self._measurements]
        y_values = np.array(values)
        cs = CubicSpline(self.ts_m, y_values, bc_type='not-a-knot')
        interpolated_values = np.array(cs(self.ts_np), dtype=np.float64)
        for i in self.missing:
            interpolated_values[i] = np.nan
        return interpolated_values.tolist()


def energy_chart(colours: Dict[str, str], measurements: Sequence[Measurement]) -> EChart:
    """
    Assumes there is at least one measurement provided.
    """
    units = KILOWATT_HOURS

    interpolator = DailyInterpolator(measurements)

    def _data(field: str) -> List[float]:
        return _ensure_monotonic(_zero(x / 1000 for x in interpolator(field)))

    solar_energy = _data('accumulated_solar_energy')
    grid_energy_import = _data('accumulated_grid_energy_import')
    grid_energy_export = _data('accumulated_grid_energy_export')
    battery_energy_charge = _data('accumulated_battery_energy_charge')
    battery_energy_discharge = _data('accumulated_battery_energy_discharge')

    options: JSONDict = {
        'backgroundColor': 'transparent',

        'tooltip': _graph_tooltip(units),

        'legend': {
            'top': 10,
            'left': 'center',
            'textStyle': {
                'color': '#888',
                'fontSize': 12
            },
        },

        'grid': {
            'left': 55,
            'right': 20,
            'top': 55,
            'bottom': 40,
            'containLabel': False
        },
        'xAxis': _xaxis(interpolator.timestamps),
        'yAxis': _yaxis('Energy', units),
        'series': [
            _create_series('Solar', solar_energy, colours['sun']),
            _create_series('Grid import', grid_energy_import, colours['grid']),
            _create_series('Grid export', grid_energy_export, colours['inverter']),
            _create_series('Battery charge', battery_energy_charge, colours['battery_charge']),
            _create_series('Battery discharge', battery_energy_discharge, colours['battery']),
        ]
    }
    return ui.echart(options)


def power_chart(colours: Dict[str, str], measurements: Sequence[Measurement]) -> EChart:
    """
    Assumes there is at least one measurement provided.
    """
    units = KILOWATTS
    interpolator = DailyInterpolator(measurements)

    def _data(field: str) -> List[float]:
        return [x / 1000 for x in interpolator(field)]

    solar_power = _data('solar_power')
    house_power = _data('house_power')
    grid_power = _data('grid_power')

    options: JSONDict = {
        'backgroundColor': 'transparent',

        'tooltip': _graph_tooltip(units),

        'legend': {
            'top': 10,
            'left': 'center',
            'textStyle': {
                'color': '#888',
                'fontSize': 12
            },
        },

        'grid': {
            'left': 55,
            'right': 20,
            'top': 55,
            'bottom': 40,
            'containLabel': False
        },
        'xAxis': _xaxis(interpolator.timestamps),
        'yAxis': _yaxis('Power', units),
        'series': [
            _create_series('Solar', solar_power, colours['sun']),
            _create_series('House', house_power, colours['house']),
            _create_series('Grid', grid_power, colours['grid']),
        ]
    }
    return ui.echart(options)
