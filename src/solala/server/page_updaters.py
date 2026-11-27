"""
Provides page updaters for NiceGUI pages.
"""

import asyncio
from abc import abstractmethod
from collections.abc import Callable, Sequence
from datetime import datetime, date
from enum import Enum
from functools import partial
from typing import final, Mapping

from nicegui import ui
from nicegui.elements.button import Button
from nicegui.elements.mixins.content_element import ContentElement

from solala.constants import GUI_DATE_FORMAT, GUI_TIME_FORMAT, Units, Constants
from solala.control import control_loop
from solala.control.loop_listener import LoopListener
from solala.control.modes_and_policies import InverterMode, InverterPolicy, BatteryMode, BatteryPolicy, ControlMode
from solala.database.measurement import Measurement
from solala.delegates.power_pricer.price import Price
from solala.delegates.solar_forecaster.solar_forecast import DailySolarForecast, SolarForecast
from solala.delegates.solar_forecaster.weather_code import WeatherCode
from solala.logger import LOGGER
from solala.register import RegisterValue, RegisterValueUnavailable
from solala.server.graph_interpolator import GraphingInterpolator
from solala.server.graphs import ChargeChart, PriceChart, PowerChart, EnergyChart
from solala.server.icons import weather_code_to_icon_url
from solala.server.infographic import Infographic
from solala.server.page_session import PageSession
from solala.server.register_filter import compile_register_filter
from solala.server.units_lookup import STATUS_UNITS
from solala.utils.json_extras import JSONDict, render_json
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


class InverterButtonUpdater(LoopListener):
    """
    Updater for inverter control buttons so that buttons reflect the
    selected mode and policy.
    """

    def __init__(
            self,
            mode_buttons: Mapping[InverterMode, Button],
            policy_buttons: Mapping[InverterPolicy, Button],
    ) -> None:
        super().__init__()
        self._mode_buttons = mode_buttons
        self._policy_buttons = policy_buttons

        for mode, button in mode_buttons.items():
            button.on_click(partial(
                self._click, mode, InverterPolicy.MANUAL
            ))
        for policy, button in policy_buttons.items():
            button.on_click(partial(
                self._click, None, policy
            ))
        _button_visual_update(
            self._mode_buttons,
            self._policy_buttons,
            None,
            InverterPolicy.MANUAL,
        )

    async def _click(self, mode: InverterMode | None, policy: InverterPolicy) -> None:
        await control_loop.set_control(
            inverter_mode=mode,
            inverter_policy=policy,
        )
        _button_visual_update(
            self._mode_buttons,
            self._policy_buttons,
            mode,
            policy,
        )

    async def update(self) -> None:
        status: ControlMode = await control_loop.get_control_mode()
        _button_visual_update(
            self._mode_buttons,
            self._policy_buttons,
            status.inverter_mode,
            status.inverter_policy,
        )


class BatteryButtonUpdater(LoopListener):
    """
    Updater for battery control buttons so that buttons reflect the
    selected mode and policy.
    """

    def __init__(
            self,
            mode_buttons: Mapping[BatteryMode, Button],
            policy_buttons: Mapping[BatteryPolicy, Button],
    ) -> None:
        super().__init__()
        self._mode_buttons = mode_buttons
        self._policy_buttons = policy_buttons

        for mode, button in mode_buttons.items():
            button.on_click(partial(
                self._click, mode, BatteryPolicy.MANUAL
            ))
        for policy, button in policy_buttons.items():
            button.on_click(partial(
                self._click, None, policy
            ))
        _button_visual_update(
            self._mode_buttons,
            self._policy_buttons,
            None,
            BatteryPolicy.MANUAL,
        )

    async def _click(self, mode: BatteryMode | None, policy: BatteryPolicy) -> None:
        await control_loop.set_control(
            battery_mode=mode,
            battery_policy=policy,
        )
        _button_visual_update(
            self._mode_buttons,
            self._policy_buttons,
            mode,
            policy,
        )

    async def update(self) -> None:
        status: ControlMode = await control_loop.get_control_mode()
        _button_visual_update(
            self._mode_buttons,
            self._policy_buttons,
            status.battery_mode,
            status.battery_policy,
        )


def _button_visual_update[Mode: Enum, Policy: Enum](
        mode_buttons: Mapping[Mode, Button],
        policy_buttons: Mapping[Policy, Button],
        current_mode: Mode | None,
        current_policy: Policy,
) -> None:
    props_on = 'color=blue'  # The button is user selected
    props_on_auto = 'color=grey-7'  # Mode button selected by auto policy
    props_off = 'color=grey-6'  # The button is off

    for mode, button in mode_buttons.items():
        accessible_label = None
        if current_mode != mode:
            props = props_off
        elif current_policy.name == 'MANUAL':
            props = props_on
            accessible_label = f'{button.text}, selected'
        else:
            props = props_on_auto
            accessible_label = f'{button.text}, selected by policy'
        button.props.set_optional('aria-label', accessible_label)
        button.props(props)

    for policy, button in policy_buttons.items():
        accessible_label = None
        if current_policy == policy:
            props = props_on
            accessible_label = f'{button.text}, selected'
        else:
            props = props_off
        button.props.set_optional('aria-label', accessible_label)
        button.props(props)


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
                 on_filter_change: Callable[[str], None] | None = None) -> None:
        super().__init__()
        self._session = session
        self._on_filter_change = on_filter_change
        control_loop.request_consumer_register_discovery()
        self._bank = control_loop.get_register_bank()
        self._values: dict[str, RegisterValue] = {}
        # Iteration tracks control-loop updates; generation tracks superseding filter reads.
        self._iteration = 0
        self._read_generation = 0
        self._read_task: asyncio.Task[None] | None = None
        self._filter = compile_register_filter('')
        self._rendered_content: str | None = None
        self._loading_element = ui.label('loading registers...').classes('w-full text-center italic')
        with ui.column().classes('w-full gap-1').style('max-width: 520px'):
            with ui.row().classes('items-center gap-2 w-full flex-nowrap'):
                self._input = ui.input(label='Filter', value=initial_filter).props(
                    'dense outlined spellcheck=false autocorrect=off autocapitalize=off'
                )
                self._input.classes('min-w-0 flex-1').style('font-size: 16px').props(
                    'input-style="font-size: 16px"'
                )
                ui.button(
                    icon='close', on_click=lambda: self._input.set_value('')
                ).props('flat round dense shrink-0')
            self._error = ui.label('invalid pattern').classes('text-red-600 w-full').set_visibility(False)
        self._registers_element = ui.code(language='nothing').classes('text-sm w-full grow').set_visibility(False)
        self._input.on_value_change(lambda event: self.set_filter(event.value))
        self.set_filter(initial_filter, initial=True)

    def set_filter(self, pattern: str, *, initial: bool = False) -> None:
        """
        Apply a valid pattern immediately; preserve the last valid pattern otherwise.
        """
        if self._session.closed:
            return
        try:
            matcher = compile_register_filter(pattern)
        except ValueError:
            self._error.set_visibility(True)
            self._input.classes(add='text-red-600')
            return
        self._error.set_visibility(False)
        self._input.classes(remove='text-red-600')
        self._filter = matcher
        self._render()
        if not initial:
            self._schedule_read()
            if self._on_filter_change is not None:
                self._on_filter_change(pattern)

    @final
    async def update(self) -> None:
        if self._session.closed:
            return
        self._iteration += 1
        control_loop.request_consumer_register_discovery()
        self._bank = control_loop.get_register_bank()
        self._values.clear()
        self._schedule_read()

    def _schedule_read(self) -> None:
        self._read_generation += 1
        if self._read_task is not None and not self._read_task.done():
            self._read_task.cancel()
        task = asyncio.create_task(self._read_values(self._iteration, self._read_generation))
        self._read_task = task
        self._session.add_task(task)

    async def _read_values(self, iteration: int, generation: int) -> None:
        bank = self._bank
        for name in bank:
            if (iteration != self._iteration or generation != self._read_generation
                    or bank is not self._bank):
                return
            if not self._filter.match(name) or name in self._values:
                continue
            try:
                value = await bank[name].get()
            except RegisterValueUnavailable:
                continue
            except asyncio.CancelledError:
                raise
            except Exception:
                # Failed reads may be retried on filter changes within the same iteration.
                LOGGER.debug('Failed to read register %s', name, exc_info=True)
                continue
            if iteration != self._iteration or generation != self._read_generation or bank is not self._bank:
                return
            self._values[name] = value
        if (iteration == self._iteration and generation == self._read_generation
                and bank is self._bank):
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
