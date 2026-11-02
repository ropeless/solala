from datetime import datetime, date, timedelta
from typing import Dict, Sequence, List, Iterable

import numpy as np
from nicegui import ui
from nicegui.elements.echart import EChart

from solala.constants import KILOWATTS, GUI_TIME_FORMAT, KILOWATT_HOURS
from solala.database.measurement import Measurement
from solala.utils.datetime_extras import ensure_date, date_to_datetime, local_time_zone
from solala.utils.json import JSONDict


class GraphingInterpolator:
    """
    Interpolates measurements data to specific 5-minute timepoints for graphing.
    """

    def __init__(self, day: date, measurements: Sequence[Measurement]):
        tz = local_time_zone()
        day = ensure_date(day, tz)
        day_as_datetime: datetime = date_to_datetime(day, tz)

        self.day: date = day
        self.timestamps: Sequence[datetime] = [
            day_as_datetime + timedelta(hours=hour, minutes=minute)
            for hour in range(24)
            for minute in range(0, 60, 5)
        ]
        self._measurements = measurements
        self._ts = np.array([dt.timestamp() for dt in self.timestamps])
        self._ts_m = np.array([measurement.timestamp.timestamp() for measurement in measurements])
        self._cache: Dict[str, List[float]] = {}

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

    # ----------------------------------------
    #  Support
    # ----------------------------------------

    def _accumulated_daily_energy(self, field: str) -> List[float]:
        return _ensure_monotonic(_zero(x / 1000 for x in self._interpolated_measurement(field)))

    def _instantaneous_power(self, field: str) -> List[float]:
        return [x / 1000 for x in self._interpolated_measurement(field)]

    def _interpolated_measurement(self, field: str) -> List[float]:
        result = self._cache.get(field)
        if result is not None:
            return result
        if len(self._measurements) == 0:
            result = []
        else:
            values = [getattr(m, field) for m in self._measurements]
            y_values = np.array(values)
            interpolated_values = np.interp(self._ts, self._ts_m, y_values, left=np.nan, right=np.nan)
            result = interpolated_values.tolist()
        self._cache[field] = result
        return result


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
        let result = 'Time: ' + params[0].axisValueLabel;

        params.forEach(item => {
            const value = Number(item.value);

            if (item.value == null || !Number.isFinite(value)) {
                return;
            }

            result += '<br/>' +
                item.marker +
                item.seriesName + ': ' +
                value.toFixed(2) + '""" + units + """';
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
    result: List[float] = []
    try:
        first = next(it)
    except StopIteration:
        return result
    while np.isnan(first):
        result.append(first)
        first = next(it)
    result.append(0)
    result.extend(val - first for val in it)
    return result


def _diff(data: Iterable[float]) -> List[float]:
    it = iter(data)
    result: List[float] = []
    try:
        prev: float = next(it)
    except StopIteration:
        return result
    while np.isnan(prev):
        result.append(prev)
        prev = next(it)
    result.append(0)
    for val in it:
        result.append(val - prev)
        prev = val
    return result


def energy_chart(colours: Dict[str, str], data: GraphingInterpolator) -> EChart:
    """
    Assumes there is at least one measurement provided.
    """
    units = KILOWATT_HOURS

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
        'xAxis': _xaxis(data.timestamps),
        'yAxis': _yaxis('Energy', units),
        'series': [
            _create_series('Solar', data.accumulated_solar_energy, colours['sun']),
            _create_series('Grid import', data.accumulated_grid_energy_import, colours['grid']),
            _create_series('Grid export', data.accumulated_grid_energy_export, colours['inverter']),
            _create_series('Battery charge', data.accumulated_battery_energy_charge, colours['battery_charge']),
            _create_series('Battery discharge', data.accumulated_battery_energy_discharge, colours['battery']),
        ]
    }
    return ui.echart(options)


def power_chart(colours: Dict[str, str], data: GraphingInterpolator) -> EChart:
    """
    Assumes there is at least one measurement provided.
    """
    units = KILOWATTS

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
        'xAxis': _xaxis(data.timestamps),
        'yAxis': _yaxis('Power', units),
        'series': [
            _create_series('Solar', data.instantaneous_solar_power, colours['sun']),
            _create_series('House', data.instantaneous_house_power, colours['house']),
            _create_series('Grid', data.instantaneous_grid_power, colours['grid']),
            _create_series('Battery', data.instantaneous_battery_power, colours['battery']),
        ]
    }
    return ui.echart(options)
