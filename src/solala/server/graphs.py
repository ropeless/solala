from datetime import datetime
from typing import Sequence, List

import numpy as np
from nicegui import ui
from nicegui.elements.echart import EChart

from solala.constants import KILOWATTS, GUI_TIME_FORMAT, KILOWATT_HOURS, PRICE_CENTS, PERCENT
from solala.server.css_colours import Colours
from solala.server.graph_interpolator import GraphingInterpolator
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


def _grid() -> JSONDict:
    return {
        'left': 30,
        'right': 5,
        'top': 55,
        'bottom': 40,
        'containLabel': True
    }


def _legend() -> JSONDict:
    return {
        'top': 10,
        'left': 'center',
        'textStyle': {
            'color': '#888',
            'fontSize': 12
        },
    }


def _x_axis(timestamps: Sequence[datetime]) -> JSONDict:
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


def _y_axis(name: str, units: str) -> JSONDict:
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


def energy_chart(data: GraphingInterpolator, colours: Colours) -> EChart:
    units = KILOWATT_HOURS
    options: JSONDict = {
        'backgroundColor': 'transparent',
        'tooltip': _graph_tooltip(units),
        'legend': _legend(),
        'grid': _grid(),
        'xAxis': _x_axis(data.timestamps),
        'yAxis': _y_axis('Energy', units),
        'series': [
            _create_series('Solar', data.accumulated_solar_energy, colours.sun),
            _create_series('Grid import', data.accumulated_grid_energy_import, colours.grid),
            _create_series('Grid export', data.accumulated_grid_energy_export, colours.inverter),
            _create_series('Battery charge', data.accumulated_battery_energy_charge, colours.battery_charge),
            _create_series('Battery discharge', data.accumulated_battery_energy_discharge, colours.battery),
        ]
    }
    return ui.echart(options).classes('w-full')


def power_chart(data: GraphingInterpolator, colours: Colours) -> EChart:
    units = KILOWATTS
    options: JSONDict = {
        'backgroundColor': 'transparent',
        'tooltip': _graph_tooltip(units),
        'legend': _legend(),
        'grid': _grid(),
        'xAxis': _x_axis(data.timestamps),
        'yAxis': _y_axis('Power', units),
        'series': [
            # _create_series('Solar', data.average_solar_power, colours['sun']),
            # _create_series('Battery', data.average_battery_power, colours['battery']),
            # _create_series('Grid', data.average_grid_power, colours['grid']),

            _create_series('Solar', data.instantaneous_solar_power, colours.sun),
            _create_series('Battery', data.instantaneous_battery_power, colours.battery),
            _create_series('Grid', data.instantaneous_grid_power, colours.grid),
            _create_series('House', data.instantaneous_house_power, colours.house),
        ]
    }
    return ui.echart(options).classes('w-full')


def price_chart(data: GraphingInterpolator) -> EChart:
    units = PRICE_CENTS

    buy_price = data.buy_price
    feed_in_price = data.feed_in_price
    forecast_buy_price = data.forecast_buy_price
    forecast_feed_in_price = data.forecast_feed_in_price

    # Ensure forecast does not overlap with actual data
    for i in range(len(buy_price)):
        if np.isfinite(buy_price[i]):
            forecast_buy_price[i] = np.nan
        if np.isfinite(feed_in_price[i]):
            forecast_feed_in_price[i] = np.nan

    options: JSONDict = {
        'backgroundColor': 'transparent',
        'tooltip': _graph_tooltip(units),
        'legend': _legend(),
        'grid': _grid(),
        'xAxis': _x_axis(data.timestamps),
        'yAxis': _y_axis('Price', units),
        'series': [
            _create_series('Buy', buy_price, '#FF6060'),
            _create_series('Feed-in', feed_in_price, '#6060FF'),
            _create_series('Buy forecast', forecast_buy_price, '#FF9090'),
            _create_series('Feed-in forecast', forecast_feed_in_price, '#9090FF'),
        ]
    }
    return ui.echart(options).classes('w-full')


def charge_chart(data: GraphingInterpolator, colours: Colours) -> EChart:
    units = PERCENT
    options: JSONDict = {
        'backgroundColor': 'transparent',
        'tooltip': _graph_tooltip(units),
        'legend': None,
        'grid': _grid(),
        'xAxis': _x_axis(data.timestamps),
        'yAxis': _y_axis('Charge', units),
        'series': [
            _create_series('Charge', data.battery_charge, colours.battery),
        ]
    }
    return ui.echart(options).classes('w-full')
