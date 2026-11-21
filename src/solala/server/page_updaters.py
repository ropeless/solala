"""
Provides page updaters for NiceGUI pages.
"""

import asyncio
from abc import abstractmethod
from collections.abc import Awaitable, Callable, Sequence
from datetime import datetime, date
from functools import partial
from typing import final

from nicegui import ui
from nicegui.elements.button import Button
from nicegui.elements.mixins.content_element import ContentElement

from solala.constants import GUI_DATE_FORMAT, GUI_TIME_FORMAT, Units, Constants
from solala.control_loop import control_loop
from solala.control_loop.loop_listener import LoopListener
from solala.control_loop.modes_and_policies import InverterMode, InverterPolicy, BatteryMode, BatteryPolicy
from solala.database.measurement import Measurement
from solala.delegates.power_pricer.price import Price
from solala.delegates.solar_forecaster.solar_forecast import DailySolarForecast, SolarForecast
from solala.delegates.solar_forecaster.weather_code import WeatherCode
from solala.logger import LOGGER
from solala.register import RegisterValue
from solala.server.graph_interpolator import GraphingInterpolator
from solala.server.graphs import ChargeChart, PriceChart, PowerChart, EnergyChart
from solala.server.icons import weather_code_to_icon_url
from solala.server.infographic import Infographic
from solala.server.page_session import PageSession
from solala.server.register_filter import compile_register_filter
from solala.server.units_lookup import STATUS_UNITS
from solala.utils.json_extras import JSONDict, json_dict, render_json
from solala.utils.type_extras import check_str
from solala.utils.time_extras import now


class StatusListener(LoopListener):
    """
    A partial abstract implementation of a LoopListener where an updater requires
    the result of `control_loop.get_status()`.

    Subclasses implement `_update()` to refresh their own page elements.
    """

    @final
    async def update(self) -> None:
        status_json: JSONDict = await control_loop.get_status()
        self._update(status_json)

    @abstractmethod
    def _update(self, status_json: JSONDict) -> None:
        ...


class InverterButtonUpdater(StatusListener):
    """
    Updater for inverter control buttons so that buttons reflect the
    selected mode and policy.
    """

    def __init__(
            self,
            inverter_enable: Button,
            inverter_disable: Button,
            inverter_zero_export: Button,
            inverter_neg_feed_in_zero_export: Button,
    ) -> None:
        super().__init__()
        self.inverter_enable = inverter_enable.on_click(partial(
            self._click, InverterMode.ENABLE, InverterPolicy.MANUAL
        ))
        self.inverter_disable = inverter_disable.on_click(partial(
            self._click, InverterMode.DISABLE, InverterPolicy.MANUAL
        ))
        self.inverter_zero_export = inverter_zero_export.on_click(partial(
            self._click, InverterMode.ZERO_EXPORT, InverterPolicy.MANUAL
        ))
        self.inverter_neg_feed_in_zero_export = inverter_neg_feed_in_zero_export.on_click(partial(
            self._click, None, InverterPolicy.NEG_FEED_IN_ZERO_EXPORT
        ))

        for button in [
            inverter_enable, inverter_disable, inverter_zero_export,
            inverter_neg_feed_in_zero_export
        ]:
            button.style('padding-top: 1px; padding-bottom: 1px;')
            button.classes('py-0 px-2 text-xs')
            button.props('color=grey dense')

    async def _click(self, mode: InverterMode | None, policy: InverterPolicy) -> None:
        await control_loop.set_control(
            inverter_mode=mode,
            inverter_policy=policy,
        )
        self._visual_update('' if mode is None else mode.name, policy.name)

    def _update(self, status_json: JSONDict) -> None:
        # Infer button states from status_json
        try:
            control_json: JSONDict = json_dict(status_json['control'])
            inverter_status: JSONDict = json_dict(control_json['inverter'])
            inverter_mode = check_str(inverter_status['mode'])
            inverter_policy = check_str(inverter_status['policy'])
        except (KeyError, TypeError, IOError, control_loop.ControlLoopError) as err:
            LOGGER.error(f'Error getting control status: {err}')
            inverter_mode = ''
            inverter_policy = ''
        self._visual_update(inverter_mode, inverter_policy)

    def _visual_update(self, inverter_mode: str, inverter_policy: str) -> None:
        inverter_button = (
            inverter_policy
            if inverter_policy != InverterPolicy.MANUAL.name
            else inverter_mode
        )

        # Set the button states
        def on_props(_on: str) -> str:
            return 'color=blue dense' if inverter_button == _on else 'color=grey dense'

        self.inverter_enable.props(on_props(InverterMode.ENABLE.name))
        self.inverter_disable.props(on_props(InverterMode.DISABLE.name))
        self.inverter_zero_export.props(on_props(InverterMode.ZERO_EXPORT.name))
        self.inverter_neg_feed_in_zero_export.props(on_props(InverterPolicy.NEG_FEED_IN_ZERO_EXPORT.name))


class BatteryButtonUpdater(StatusListener):
    """
    Updater for battery control buttons so that buttons reflect the
    selected mode and policy.
    """

    def __init__(
            self,
            battery_enable: Button,
            battery_disable: Button,
            battery_force_charge: Button,
            battery_force_discharge: Button,
            battery_charge_only: Button,
            battery_discharge_only: Button,
            battery_cheap_force_charge: Button,
    ) -> None:
        super().__init__()
        self.battery_enable = battery_enable.on_click(partial(
            self._click, BatteryMode.ENABLE, BatteryPolicy.MANUAL
        ))
        self.battery_disable = battery_disable.on_click(partial(
            self._click, BatteryMode.DISABLE, BatteryPolicy.MANUAL
        ))
        self.battery_force_charge = battery_force_charge.on_click(partial(
            self._click, BatteryMode.FORCE_CHARGE, BatteryPolicy.MANUAL
        ))
        self.battery_force_discharge = battery_force_discharge.on_click(partial(
            self._click, BatteryMode.FORCE_DISCHARGE, BatteryPolicy.MANUAL
        ))
        self.battery_charge_only = battery_charge_only.on_click(partial(
            self._click, BatteryMode.CHARGE_ONLY, BatteryPolicy.MANUAL
        ))
        self.battery_discharge_only = battery_discharge_only.on_click(partial(
            self._click, BatteryMode.DISCHARGE_ONLY, BatteryPolicy.MANUAL
        ))
        self.battery_cheap_force_charge = battery_cheap_force_charge.on_click(partial(
            self._click, None, BatteryPolicy.CHEAP_CHARGE
        ))

        for button in [
            battery_enable, battery_disable, battery_force_charge, battery_force_discharge,
            battery_charge_only, battery_discharge_only, battery_cheap_force_charge
        ]:
            button.style('padding-top: 1px; padding-bottom: 1px;')
            button.classes('py-0 px-2 text-xs')
            button.props('color=grey dense')

    async def _click(self, mode: BatteryMode | None, policy: BatteryPolicy) -> None:
        await control_loop.set_control(
            battery_mode=mode,
            battery_policy=policy,
        )
        self._visual_update('' if mode is None else mode.name, policy.name)

    def _update(self, status_json: JSONDict) -> None:
        # Infer button states from status_json
        try:
            control_json: JSONDict = json_dict(status_json['control'])
            battery_status: JSONDict = json_dict(control_json['battery'])
            battery_mode = check_str(battery_status['mode'])
            battery_policy = check_str(battery_status['policy'])
        except (KeyError, TypeError, IOError, control_loop.ControlLoopError) as err:
            LOGGER.error(f'Error getting control status: {err}')
            battery_mode = ''
            battery_policy = ''
        self._visual_update(battery_mode, battery_policy)

    def _visual_update(self, battery_mode: str, battery_policy: str) -> None:
        battery_button = (
            battery_policy
            if battery_policy != BatteryPolicy.MANUAL.name
            else battery_mode
        )

        def on_props(_on: str) -> str:
            return 'color=blue dense' if battery_button == _on else 'color=grey dense'

        self.battery_enable.props(on_props(BatteryMode.ENABLE.name))
        self.battery_disable.props(on_props(BatteryMode.DISABLE.name))
        self.battery_force_charge.props(on_props(BatteryMode.FORCE_CHARGE.name))
        self.battery_force_discharge.props(on_props(BatteryMode.FORCE_DISCHARGE.name))
        self.battery_charge_only.props(on_props(BatteryMode.CHARGE_ONLY.name))
        self.battery_discharge_only.props(on_props(BatteryMode.DISCHARGE_ONLY.name))
        self.battery_cheap_force_charge.props(on_props(BatteryPolicy.CHEAP_CHARGE.name))


class StatusUpdater(StatusListener):
    """
    Render the control-loop status as formatted JSON in a page element.
    """

    def __init__(
            self,
            status_element: ContentElement,
    ) -> None:
        super().__init__()
        self.status_element = status_element

    def _update(self, status_json: JSONDict) -> None:
        # Set the content of the status and infographic elements
        json_as_str = render_json(status_json, float_format='.2f', units=STATUS_UNITS)
        self.status_element.set_content(json_as_str)


class InfographicUpdater(StatusListener):
    """
    Render the SVG power-flow infographic in a page element.
    """

    def __init__(self, infographic_element: ContentElement) -> None:
        super().__init__()
        self.infographic_element = infographic_element
        self.infographic = Infographic()

    def _update(self, status_json: JSONDict) -> None:
        self.infographic.make_from_status(status_json)
        self.infographic_element.set_content(self.infographic.as_svg())


class RegistersUpdater(LoopListener):
    """
    Display filtered register names and values from the current control-loop iteration.
    """

    def __init__(self, session: PageSession, initial_filter: str = '',
                 on_filter_change: Callable[[str], Awaitable[None]] | None = None) -> None:
        super().__init__()
        self._session = session
        self._on_filter_change = on_filter_change
        self._bank = control_loop.get_register_bank()
        self._values: dict[str, RegisterValue] = {}
        self._iteration = 0
        self._read_task: asyncio.Task[None] | None = None
        self._filter = compile_register_filter('')
        self._pattern = ''
        self._rendered_content: str | None = None
        self._loading_element = ui.label('loading registers...').classes('w-full text-center italic')
        with ui.row().classes('items-center gap-2'):
            self._input = ui.input(label='Filter', value=initial_filter).props('dense outlined spellcheck=false autocorrect=off autocapitalize=off')
            self._input.style('width: 400px; max-width: 100%')
            ui.button(icon='close', on_click=lambda: self._input.set_value('')).props('flat round dense')
            self._error = ui.label('invalid pattern').classes('text-red-600').set_visibility(False)
        self._registers_element = ui.code(language='nothing').classes('text-sm w-full grow').set_visibility(False)
        self._input.on_value_change(lambda event: self.set_filter(event.value))
        self.set_filter(initial_filter)

    def set_filter(self, pattern: str) -> None:
        """
        Apply a valid pattern immediately; preserve the last valid pattern otherwise.
        """
        try:
            matcher = compile_register_filter(pattern)
        except ValueError:
            self._error.set_visibility(True)
            self._input.classes(add='text-red-600')
            return
        self._error.set_visibility(False)
        self._input.classes(remove='text-red-600')
        self._pattern = pattern
        self._filter = matcher
        self._render()
        self._schedule_read()
        if self._on_filter_change is not None:
            self._session.add_task(asyncio.create_task(self._on_filter_change(pattern)))

    @final
    async def update(self) -> None:
        self._iteration += 1
        self._bank = control_loop.get_register_bank()
        self._values.clear()
        self._schedule_read()

    def _schedule_read(self) -> None:
        if self._read_task is not None and not self._read_task.done():
            self._read_task.cancel()
        task = asyncio.create_task(self._read_values(self._iteration))
        self._read_task = task
        self._session.add_task(task)

    async def _read_values(self, iteration: int) -> None:
        bank = self._bank
        for name in bank:
            if iteration != self._iteration or bank is not self._bank:
                return
            if not self._filter.match(name) or name in self._values:
                continue
            try:
                value = await bank[name].get()
            except asyncio.CancelledError:
                raise
            except Exception:
                continue
            if iteration != self._iteration or bank is not self._bank:
                return
            self._values[name] = value
        if iteration == self._iteration and bank is self._bank:
            self._render()

    def _render(self) -> None:
        names = [name for name in self._bank if self._filter.match(name)]
        lines: list[str] = []
        for name in names:
            if name in self._values:
                rendered = render_json(
                    {name: self._values[name]},
                    float_format='.2f',
                    remove_key_underscores=False,
                    remove_value_underscores=False,
                )
                lines.append(rendered)
            else:
                lines.append(name)
        content = '\n'.join(lines)
        if content != self._rendered_content:
            self._registers_element.set_content(content)
            self._rendered_content = content
        self._loading_element.set_visibility(False)
        self._registers_element.set_visibility(True)


class PriceForecastUpdater(LoopListener):
    """
    Render a price forecast table with demand-window row highlighting.

    The table is rebuilt when the forecast sequence object changes.
    """

    def __init__(self, element: ui.element) -> None:
        super().__init__()
        self._prev: Sequence[Price] | None = None
        self._element = element

    @final
    async def update(self) -> None:
        price_forecast: Sequence[Price]
        demand_window: tuple[datetime, datetime] | None

        price_forecast, demand_window = await asyncio.gather(
            control_loop.get_price_forecast(),
            control_loop.get_demand_window(date.today())
        )
        if self._prev is not price_forecast:
            self._prev = price_forecast
            self._update(price_forecast, demand_window)

    def _update(self, price_forecast: Sequence[Price], demand_window: tuple[datetime, datetime] | None) -> None:

        def _is_demand_window(_price: Price) -> bool:
            if demand_window is None:
                return False
            demand_start, demand_end = demand_window
            return _price.start_time < demand_end and _price.end_time > demand_start

        # Recreate the price forecast table
        self._element.clear()
        with self._element:

            if len(price_forecast) == 0:
                with ui.card().classes('w-full bg-white rounded-xl border border-[#e1e6ea] p-6'):
                    ui.icon('query_stats').classes('text-3xl text-[#a1a9ae]')
                    ui.label('No price forecast available').classes('text-lg font-semibold')
                    ui.label('There are currently no forecast prices to display.').classes('text-sm text-gray-500')
                return

            forecast_date = price_forecast[0].start_time.date()

            with ui.row().classes('items-center gap-2 mb-5 h-[42px]'):
                with ui.element('div').classes('w-8 h-8 flex items-center justify-center shrink-0'):
                    ui.icon('calendar_today', size='20px').classes('text-gray-500')
                ui.label(forecast_date.strftime(GUI_DATE_FORMAT)).classes('text-sm text-gray-500')

            # Forecast table
            with ui.column().classes('w-full gap-3'):
                with ui.element('div').classes('price-table'):
                    with ui.element('div').classes('price-row price-header'):
                        ui.label('Time')
                        ui.label('Buy').classes('text-right')
                        ui.label('Feed-in').classes('text-right')
                        ui.label('Renewables').classes('text-right')

                    for i, price in enumerate(price_forecast):
                        row_classes = 'price-row'

                        if _is_demand_window(price):
                            row_classes += ' price-row-demand'
                        elif i % 2 == 1:
                            row_classes += ' price-row-alt'

                        with ui.element('div').classes(row_classes):
                            ui.label(price.start_time.strftime(GUI_TIME_FORMAT)).classes('price-time')

                            buy_class = _buy_price_class(price.buy_price)
                            ui.label(f'{price.buy_price:.1f}').classes(f'price-number {buy_class}')

                            feed_class = _feed_in_price_class(price.feed_in_price)
                            ui.label(f'{price.feed_in_price:.1f}').classes(f'price-number {feed_class}')

                            ui.label(f'{price.renewables:.1f}{Units.PERCENT}').classes('price-number')


class SolarForecastUpdater(LoopListener):
    """
    Render a selected day's solar forecast and estimated generation.

    A call to `set_day()` will change the day and schedule a page-owned refresh task.
    Displays a "loading" message until the forecast is available.
    """

    def __init__(self, element: ui.element, session: PageSession) -> None:
        super().__init__()
        self._session = session
        self._prev: DailySolarForecast | None = None
        self._day: date = date.today()
        self._element: ui.element = element
        self._show_loading()

    @final
    async def update(self) -> None:
        solar_forecast: DailySolarForecast = await control_loop.get_solar_forecast(self._day)
        if self._prev is not solar_forecast:
            self._prev = solar_forecast
            self._update(solar_forecast)

    @property
    def day(self) -> date:
        return self._day

    async def set_day(self, day: date) -> None:
        """
        Select a forecast date and schedule a refresh of its table.

        Args:
            day: Date to display.
        """
        self._show_loading()
        self._day = day
        self._session.add_task(asyncio.create_task(self.update()))

    def _show_loading(self) -> None:
        self._element.clear()
        with self._element:
            ui.label('loading solar forecast...').classes('text-center italic')

    def _update(self, solar_forecast: DailySolarForecast) -> None:
        _now = now()

        def _forecast_for_now(_forecast: SolarForecast) -> bool:
            return _forecast.start_time <= _now < _forecast.end_time

        # Recreate the solar forecast table if needed
        self._element.clear()
        with self._element:
            forecasts = solar_forecast.forecasts
            if len(forecasts) == 0:
                with ui.card().classes('w-full bg-white rounded-xl border border-[#e1e6ea] p-6'):
                    ui.icon('query_stats').classes('text-3xl text-[#a1a9ae]')
                    ui.label('No solar forecast available').classes('text-lg font-semibold')
                return

            with ui.row().classes('items-center gap-2 mb-5'):
                ui.label('Daily generation estimate:').classes('text-sm text-gray-500')
                total = f'{solar_forecast.total_forecast_energy() / 1000:.2f}'
                ui.label(f'{total}{Units.KILOWATT_HOURS}').classes('solar-number')

            # Forecast table
            with ui.column().classes('w-full gap-3'):
                with ui.element('div').classes('solar-table'):
                    with ui.element('div').classes('solar-row solar-header'):
                        ui.label('Time')
                        ui.label('Temp').classes('text-right')
                        ui.label('Sky').classes('text-right')
                        ui.label('Irradiance').classes('text-right')
                        ui.label('Power').classes('text-right')

                    forecast: SolarForecast
                    for i, forecast in enumerate(solar_forecast):
                        row_classes = 'solar-row'
                        if _forecast_for_now(forecast):
                            row_classes += ' solar-row-now'
                        elif i % 2 == 1:
                            row_classes += ' solar-row-alt'

                        icon: str | None = weather_code_to_icon_url(
                            forecast.weather, Constants.ANIMATE_WEATHER_ICONS
                        )

                        with ui.element('div').classes(row_classes):
                            ui.label(
                                forecast.start_time.strftime(GUI_TIME_FORMAT)
                            ).classes('solar-time')

                            ui.label(
                                f'{int(forecast.temperature + 0.5)}{Units.CELSIUS}'
                            ).classes('solar-number')

                            with ui.element('div').classes('solar-weather-cell'):
                                if icon is not None:
                                    ui.image(icon).classes('solar-weather-image')

                            if forecast.weather == WeatherCode.NIGHT:
                                ui.label('.').classes('solar-number')
                                ui.label('.').classes('solar-number')
                            else:
                                ui.label(
                                    f'{int(forecast.irradiance + 0.5)}'
                                ).classes('solar-number')

                                ui.label(
                                    f'{forecast.power / 1000:.2f}{Units.KILOWATTS}'
                                ).classes('solar-number')


class ChartUpdater(LoopListener):
    """
    Fetch and display charts for the selected day.

    Chart data are fetched concurrently and combined using a `GraphingInterpolator`.
    """

    def __init__(self, element: ui.element, session: PageSession) -> None:
        super().__init__()
        self._session = session
        self._prev: DailySolarForecast | None = None
        self._day: date = date.today()

        with element:
            self._loading = ui.label('loading graphs...').classes('text-center italic').set_visibility(True)
            self._graphs = ui.element('div').set_visibility(False)

            with self._graphs:
                self._charge_chart = ChargeChart(session.colours)
                self._price_chart = PriceChart(session.colours)
                self._power_chart = PowerChart(
                    session.colours, session.graph_series.get('Power'), self._legend_changed,
                )
                self._energy_chart = EnergyChart(
                    session.colours, session.graph_series.get('Energy'), self._legend_changed,
                )

        self._session.add_task(asyncio.create_task(self.update()))

    async def _legend_changed(self, chart: str, selected: dict[str, bool]) -> None:
        """
        Apply a legend selection to all carousel slides and persist it.
        """
        if self._session.closed:
            return
        self._session.graph_series[chart] = selected.copy()
        if self._session.on_legend_change is not None:
            await self._session.on_legend_change(chart, selected)

    def sync_legend(self, chart: str, selected: dict[str, bool]) -> None:
        """
        Apply a shared legend selection to this slide.
        """
        if chart == 'Power':
            self._power_chart.set_selected_series(selected)
        elif chart == 'Energy':
            self._energy_chart.set_selected_series(selected)

    @property
    def day(self) -> date:
        return self._day

    async def set_day(self, day: date) -> None:
        """
        Select a chart date and schedule a refresh of the graphs.

        Args:
            day: Date to display.
        """
        self._show_loading()
        self._day = day
        self._session.add_task(asyncio.create_task(self.update()))

    @final
    async def update(self) -> None:
        graph_interpolator = await self._get_data()
        self._update(graph_interpolator)

    async def _get_data(self) -> GraphingInterpolator:
        day = self._day
        measurements: Sequence[Measurement]
        price_forecast: Sequence[Price]
        solar_forecast: DailySolarForecast
        demand_window: tuple[datetime, datetime] | None
        measurements, price_forecast, demand_window, solar_forecast = await asyncio.gather(
            control_loop.solala_database_measurements(day),
            control_loop.get_price_forecast(),
            control_loop.get_demand_window(day),
            control_loop.get_solar_forecast(day),
        )
        return GraphingInterpolator(day, measurements, price_forecast, solar_forecast, demand_window)

    def _show_loading(self) -> None:
        self._graphs.set_visibility(False)
        self._loading.set_visibility(True)

    def _update(self, graph_interpolator: GraphingInterpolator) -> None:
        self._loading.set_visibility(False)
        self._charge_chart.update(graph_interpolator)
        self._price_chart.update(graph_interpolator)
        self._power_chart.update(graph_interpolator)
        self._energy_chart.update(graph_interpolator)
        self._graphs.set_visibility(True)


def _buy_price_class(price: float) -> str:
    """
    Select the CSS class for the configured electricity purchase price bands.
    """
    if price >= Constants.BUY_PRICE_RED:
        return 'price-buy-high'
    elif price >= Constants.BUY_PRICE_AMBER:
        return 'price-buy-okay'
    else:
        return 'price-buy-good'


def _feed_in_price_class(price: float) -> str:
    """
    Select the CSS class for nonnegative or negative feed-in prices.
    """
    if price >= 0:
        return 'price-feed-in-okay'
    else:
        return 'price-feed-in-bad'
