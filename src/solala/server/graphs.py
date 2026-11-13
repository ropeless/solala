from abc import abstractmethod, ABC
from dataclasses import dataclass
from datetime import datetime
from collections.abc import Sequence

import numpy as np
from nicegui import ui

from solala.constants import Units, GUI_TIME_FORMAT
from solala.server.css_colours import Colours, rgba
from solala.server.graph_interpolator import GraphingInterpolator
from solala.utils.json_extras import JSONDict, JSONValue

LINE_WIDTH: float = 1.75
DASHED = [3, 3]


@dataclass
class SeriesData:
    data: Sequence[list[float] | list[int]]
    demand_window: tuple[datetime, datetime] | None = None


class SolalaChart(ABC):
    def __init__(
            self,
            name: str,
            units: str,
            series: list[JSONDict],
            demand_window_colour: str = '',
            show_legend: bool = True,
    ) -> None:
        options: dict[str, JSONValue] = {
            'backgroundColor': 'transparent',
            'tooltip': _graph_tooltip(units),
            'grid': _grid(legend_space=show_legend),
            'xAxis': _x_axis(),
            'yAxis': _y_axis(name, units),
            'series': series,
        }
        if show_legend:
            options['legend'] = _legend()
        self.chart = ui.echart(options).classes('w-full')
        self.demand_window_colour = demand_window_colour

    def update(self, data: GraphingInterpolator) -> None:
        series = self.chart.options['series']
        timestamps = [timestamp.strftime(GUI_TIME_FORMAT) for timestamp in data.timestamps]

        self.chart.options['xAxis']['data'] = timestamps

        series_data: SeriesData = self._get_series_data(data)
        if len(series_data.data) != len(series):
            raise RuntimeError('Wrong number of series provided')

        with self.chart.client:
            for s, d in zip(series, series_data.data):
                s['data'] = d

            # Configure the demand window
            if series_data.demand_window is not None:
                series[0]['markArea'] = _demand_window(*series_data.demand_window, colour=self.demand_window_colour)
            else:
                series[0]['markArea'] = None

            self.chart.update()

    @abstractmethod
    def _get_series_data(self, data: GraphingInterpolator) -> SeriesData:
        ...


class EnergyChart(SolalaChart):
    def __init__(self, colours: Colours) -> None:
        super().__init__(
            'Energy',
            Units.KILOWATT_HOURS,
            [
                _create_series('Solar', colours.sun),
                _create_series('Forecast', colours.sun, DASHED, 0),
                _create_series('Import', colours.grid),
                _create_series('Export', colours.inverter),
                _create_series('Charge', colours.battery_charge),
                _create_series('Discharge', colours.battery),
            ]
        )

    def _get_series_data(self, data: GraphingInterpolator) -> SeriesData:
        return SeriesData(
            data=(
                data.accumulated_solar_energy,
                data.forecast_accumulated_solar_energy,
                data.accumulated_grid_energy_import,
                data.accumulated_grid_energy_export,
                data.accumulated_battery_energy_charge,
                data.accumulated_battery_energy_discharge,
            )
        )


class PowerChart(SolalaChart):
    def __init__(self, colours: Colours) -> None:
        super().__init__(
            'Power',
            Units.KILOWATTS,
            [
                _create_series('Solar', colours.sun),
                _create_series('Forecast', colours.sun, DASHED, 0),
                _create_series('Grid', colours.grid),
                _create_series('Battery', colours.battery),
                _create_series('House', colours.house),
            ]
        )

    def _get_series_data(self, data: GraphingInterpolator) -> SeriesData:
        return SeriesData(
            data=(
                data.instantaneous_solar_power,
                data.forecast_solar_power,
                data.instantaneous_grid_power,
                data.instantaneous_battery_power,
                data.instantaneous_house_power,
            )
        )


class PriceChart(SolalaChart):
    def __init__(self, colours: Colours) -> None:
        super().__init__(
            'Price',
            Units.PRICE_CENTS,
            [
                _create_series('Buy', colours.grid_import),
                _create_series('Feed-in', colours.grid_export, area_alpha=0),
                _create_series('Buy Forecast', colours.grid_import, DASHED, 0),
                _create_series('Feed-in Forecast', colours.grid_export, DASHED, 0),
            ],
            demand_window_colour=colours.demand_window,
            show_legend=False,
        )

    def _get_series_data(self, data: GraphingInterpolator) -> SeriesData:
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

        return SeriesData(
            data=(
                buy_price,
                feed_in_price,
                forecast_buy_price,
                forecast_feed_in_price,
            ),
            demand_window=data.demand_window,
        )


class ChargeChart(SolalaChart):
    def __init__(self, colours: Colours) -> None:
        super().__init__(
            'Charge',
            Units.PERCENT,
            [_create_series('Charge', colours.battery)],
            show_legend=False,
        )

    def _get_series_data(self, data: GraphingInterpolator) -> SeriesData:
        return SeriesData(data=(data.battery_charge,))


# ====================================================================
#  Support functions
# ====================================================================


def _demand_window(start: datetime, end: datetime, colour: str, title: str = 'demand') -> JSONDict:
    return {
        'silent': True,
        'itemStyle': {
            'color': rgba(colour),
            'borderColor': rgba(colour, alpha=0.2),
            'borderWidth': 1,
            'borderType': 'solid',

        },
        'label': {
            'show': True,
            'position': 'insideTop',
            'color': colour,
            'fontSize': 12,
            'formatter': title,
        },
        'data': [
            [
                {'xAxis': start.strftime(GUI_TIME_FORMAT)},
                {'xAxis': end.strftime(GUI_TIME_FORMAT)},
            ],
        ],
    }


def _create_series(
        name: str,
        colour: str,
        line_type: str | list = 'solid',
        area_alpha: float = 0.1,
) -> JSONDict:
    options: dict[str, JSONValue] = {
        'name': name,
        'type': 'line',
        'data': [],
        'smooth': 0.25,
        'showSymbol': False,
        'color': colour,
        'lineStyle': {
            'width': LINE_WIDTH,
            'color': colour,
            'type': line_type,
        },
    }
    if area_alpha > 0:
        options['areaStyle'] = {'color': rgba(colour, area_alpha)}

    return options


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


def _grid(legend_space: bool) -> JSONDict:
    return {
        'left': 0,
        'right': 0,
        'top': 85 if legend_space else 40,
        'bottom': 40,
        'containLabel': True,
    }


def _legend() -> JSONDict:
    return {
        'type': 'plain',
        'top': 0,
        'left': 10,
        'right': 0,
        'orient': 'horizontal',
        'width': 'auto',
        'itemGap': 15,
        'textStyle': {
            'color': '#888',
            'fontSize': 12
        },
    }


def _x_axis() -> JSONDict:
    return {
        'type': 'category',
        'boundaryGap': False,
        'data': [],
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
        'nameTextStyle': {
            'color': '#888',
            'align': 'left'
        },
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
