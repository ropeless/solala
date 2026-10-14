import asyncio
import json
from abc import abstractmethod
from asyncio import AbstractEventLoop
from datetime import date, timedelta
from functools import partial
from typing import Mapping, final, Optional, Dict, List

from nicegui import ui, app, events
from nicegui.elements.button import Button
from nicegui.elements.mixins.content_element import ContentElement

from solala import server_log
from solala.control_loop import control_loop
from solala.control_loop.control_loop import LoopListener
from solala.control_loop.modes_and_policies import BatteryMode, BatteryPolicy, InverterMode, InverterPolicy
from solala.power_pricer.power_pricer import Price
from solala.resources import IMAGE_FILES, RESOURCES, CSS_FILES
from solala.server_constants import APP_NAME, MAX_LOG_HISTORY, APP_SUBTITLE, BUY_PRICE_RED, BUY_PRICE_AMBER
from solala.server_constants import LOGGER
from solala.server_infographic import Infographic, CLICK_ID_HOME, CLICK_ID_SUN, CLICK_ID_GRID, CLICK_ID_BATTERY, \
    CLICK_ID_INVERTER
from solala.solar_forecaster.solar_forecaster import DailySolarForecast, SolarForecast
from solala.units import PRICE_CENTS, PERCENT, WATTS, VOLTS, AMPS, SECONDS, MINUTES, HOURS, WATT_HOURS, DEGREES, \
    KILOWATT_HOURS, CELSIUS, KILOWATTS
from solala.utils.dict_extras import dict_merge
from solala.utils.json import JSONDict, json_dict, render_json, filter_json, json_str

# --------------------------------------------------------------------
# Main styling
# --------------------------------------------------------------------

_HEAD_HTML = r'''
<link rel="manifest" href="/manifest.json">
<link rel="stylesheet" href="/css/solala.css">
<link rel="icon" type="image/png" href="/images/images/solala-32x32.png">
'''

# Units for pretty printing status
_PARAMETERS_UNITS: Mapping[str, str] = {
    'start_charge_price_threshold': PRICE_CENTS,
    'stop_charge_price_threshold': PRICE_CENTS,
    'disable_export_price_threshold': PRICE_CENTS,
    'enable_export_price_threshold': PRICE_CENTS,
}
_STATUS_UNITS: Mapping[str, str] = dict_merge(
    {
        'buy_price': PRICE_CENTS,
        'feed_in_price': PRICE_CENTS,
        'renewables': PERCENT,
        'state_of_charge': PERCENT,
        'power_limit': PERCENT,
        'grid_power': WATTS,
        'solar_power': WATTS,
        'battery_power': WATTS,
        'house_power': WATTS,
        'consumers_total': WATTS,
        'consumers_remaining': WATTS,
        'power': WATTS,
        'voltage': VOLTS,
        'current': AMPS,
        'capacity': WATTS,
        'forecast_generation': WATT_HOURS,
    },
    _PARAMETERS_UNITS,
)
_CONSTANTS_UNITS: Mapping[str, str] = {
    'LOOP_TIME': SECONDS,
    'LOOP_MIN_SLEEP_TIME': SECONDS,
    'CONTROL_DURATION': SECONDS,
    'PRICE_LOOK_AHEAD': MINUTES,
    'PRICE_SETTLE_CHECK': SECONDS,
    'PRICE_FORECAST_DURATION': HOURS,
    'PRICE_FORECAST_AGE': MINUTES,
    'SOLAR_FORECAST_AGE': MINUTES,
}
_CONNECTION_UNITS: Mapping[str, str] = {
    'latitude': DEGREES,
    'longitude': DEGREES,
    'panel_orientation': DEGREES,
    'panel_tilt': DEGREES,
}


class StatusListener(LoopListener):

    def __init__(self):
        super().__init__()
        self._main_loop: AbstractEventLoop = asyncio.get_running_loop()

    @final
    def update(self) -> None:
        """
        Thread safe update.
        """
        status_json = control_loop.get_status()
        self._main_loop.call_soon_threadsafe(partial(self._update, status_json))

    @abstractmethod
    def _update(self, status_json: JSONDict) -> None:
        ...


class RegistersListener(LoopListener):

    def __init__(self):
        super().__init__()
        self._main_loop: AbstractEventLoop = asyncio.get_running_loop()

    @final
    def update(self) -> None:
        """
        Thread safe update.
        """
        register_values: Dict[str, int | float | str | bool] = control_loop.get_registers()
        self._main_loop.call_soon_threadsafe(partial(self._update, register_values))

    def _update(self, registers_json: JSONDict) -> None:
        ...


class PriceForecastListener(LoopListener):

    def __init__(self):
        super().__init__()
        self._main_loop: AbstractEventLoop = asyncio.get_running_loop()

    @final
    def update(self) -> None:
        """
        Thread safe update.
        """
        price_forecast: List[Price] = control_loop.get_price_forecast()
        self._main_loop.call_soon_threadsafe(partial(self._update, price_forecast))

    def _update(self, price_forecast: List[Price]) -> None:
        ...


class SolarForecastListener(LoopListener):

    def __init__(self, day: date):
        super().__init__()
        self._main_loop: AbstractEventLoop = asyncio.get_running_loop()
        self.day: date = day

    @final
    def update(self) -> None:
        """
        Thread safe update.
        """
        solar_forecast: DailySolarForecast = control_loop.get_solar_forecast(self.day)
        self._main_loop.call_soon_threadsafe(partial(self._update, solar_forecast))

    def _update(self, solar_forecast: DailySolarForecast) -> None:
        ...


def _register_listener(listener: LoopListener) -> None:
    listener.update()
    ui.context.client.on_disconnect(partial(control_loop.remove_listener, listener))
    control_loop.add_listener(listener)


class InverterButtonUpdater(StatusListener):

    def __init__(
            self,
            inverter_enable: Button,
            inverter_disable: Button,
            inverter_zero_export: Button,
            inverter_neg_feed_in_zero_export: Button,
    ):
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

    def _click(self, mode: Optional[InverterMode], policy: InverterPolicy) -> None:
        control_loop.set_control(
            inverter_mode=mode,
            inverter_policy=policy,
        )
        self._visual_update('' if mode is None else mode.name, policy.name)

    def _update(self, status_json: JSONDict) -> None:
        # Infer button states from status_json
        try:
            control_json: JSONDict = json_dict(status_json['control'])
            inverter_status: JSONDict = json_dict(control_json['inverter'])
            inverter_mode = json_str(inverter_status['mode'])
            inverter_policy = json_str(inverter_status['policy'])
        except (KeyError, TypeError, IOError, control_loop.ControlLoopError) as err:
            LOGGER.error(f'Error getting control status: {err}')
            inverter_mode = ''
            inverter_policy = ''
        self._visual_update(inverter_mode, inverter_policy)

    def _visual_update(self, inverter_mode: str, inverter_policy: str):
        inverter_button = (
            inverter_policy
            if inverter_policy != InverterPolicy.MANUAL.name
            else inverter_mode
        )

        # Set the button states
        def on_props(_on: str) -> str:
            return 'color=blue dense' if inverter_button == _on else 'color=grey dense'

        self.inverter_enable.props(on_props('ENABLE'))
        self.inverter_disable.props(on_props('DISABLE'))
        self.inverter_zero_export.props(on_props('ZERO_EXPORT'))
        self.inverter_neg_feed_in_zero_export.props(on_props('NEG_FEED_IN_ZERO_EXPORT'))


class BatteryButtonUpdater(StatusListener):

    def __init__(
            self,
            battery_enable: Button,
            battery_disable: Button,
            battery_force_charge: Button,
            battery_force_discharge: Button,
            battery_cheap_force_discharge: Button,
    ):
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
        self.battery_cheap_force_discharge = battery_cheap_force_discharge.on_click(partial(
            self._click, None, BatteryPolicy.CHEAP_CHARGE
        ))

        for button in [
            battery_enable, battery_disable, battery_force_charge, battery_force_discharge,
            battery_cheap_force_discharge
        ]:
            button.style('padding-top: 1px; padding-bottom: 1px;')
            button.classes('py-0 px-2 text-xs')

    def _click(self, mode: Optional[BatteryMode], policy: BatteryPolicy) -> None:
        control_loop.set_control(
            battery_mode=mode,
            battery_policy=policy,
        )
        self._visual_update('' if mode is None else mode.name, policy.name)

    def _update(self, status_json: JSONDict) -> None:
        # Infer button states from status_json
        try:
            control_json: JSONDict = json_dict(status_json['control'])
            battery_status: JSONDict = json_dict(control_json['battery'])
            battery_mode = json_str(battery_status['mode'])
            battery_policy = json_str(battery_status['policy'])
        except (KeyError, TypeError, IOError, control_loop.ControlLoopError) as err:
            LOGGER.error(f'Error getting control status: {err}')
            battery_mode = ''
            battery_policy = ''
        self._visual_update(battery_mode, battery_policy)

    def _visual_update(self, battery_mode: str, battery_policy: str):
        battery_button = (
            battery_policy
            if battery_policy != BatteryPolicy.MANUAL.name
            else battery_mode
        )

        def on_props(_on: str) -> str:
            return 'color=blue dense' if battery_button == _on else 'color=grey dense'

        self.battery_enable.props(on_props('ENABLE'))
        self.battery_disable.props(on_props('DISABLE'))
        self.battery_force_charge.props(on_props('FORCE_CHARGE'))
        self.battery_force_discharge.props(on_props('FORCE_DISCHARGE'))
        self.battery_cheap_force_discharge.props(on_props('CHEAP_FORCE_DISCHARGE'))


class StatusUpdater(StatusListener):

    def __init__(
            self,
            status_element: ContentElement,
    ):
        super().__init__()
        self.status_element = status_element

    def _update(self, status_json: JSONDict) -> None:
        # Set the content of the status and infographic elements
        json_as_str = render_json(status_json, float_format='.2f', units=_STATUS_UNITS)
        self.status_element.set_content(json_as_str)


class InfographicUpdater(StatusListener):
    def __init__(
            self,
            infographic_element: ContentElement,
    ):
        super().__init__()
        self.infographic_element = infographic_element
        self.infographic = Infographic()

    def _update(self, status_json: JSONDict) -> None:
        self.infographic.make_from_status(status_json)
        self.infographic_element.set_content(self.infographic.as_svg())


class RegistersUpdater(RegistersListener):

    def __init__(
            self,
            registers_element: ContentElement,
            match: Optional[str],
    ):
        super().__init__()
        self.registers_element = registers_element
        self.match = match

    def _update(self, registers_json: JSONDict) -> None:
        if self.match is not None:
            registers_json = filter_json(registers_json, self.match)
        json_as_str = render_json(
            registers_json,
            float_format='.2f',
            remove_key_underscores=False,
            remove_value_underscores=False,
        )
        self.registers_element.set_content(json_as_str)


class PriceForecastUpdater(PriceForecastListener):
    def __init__(self, element: ui.element):
        super().__init__()
        self._element = element

    def _update(self, price_forecast: List[Price]) -> None:
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

            with ui.row().classes('items-center gap-2 mb-5'):
                ui.icon('calendar_today').classes('text-lg text-gray-500')
                ui.label(forecast_date.strftime('%A, %d %B %Y')).classes('text-sm text-gray-500')

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
                        if i % 2 == 1:
                            row_classes += ' price-row-alt'

                        with ui.element('div').classes(row_classes):
                            ui.label(price.start_time.strftime('%H:%M')).classes('price-time')

                            buy_class = _buy_price_class(price.buy_price)
                            ui.label(f'{price.buy_price:.1f}').classes(f'price-number {buy_class}')

                            feed_class = _feed_in_price_class(price.feed_in_price)
                            ui.label(f'{price.feed_in_price:.1f}').classes(f'price-number {feed_class}')

                            ui.label(f'{price.renewables:.1f}{PERCENT}').classes('price-number')


class SolarForecastUpdater(SolarForecastListener):
    def __init__(self, element: ui.element, day: date):
        super().__init__(day)
        self._element = element

    def set_day(self, day: date) -> None:
        self.day = day
        self._element.clear()
        forecast: Optional[DailySolarForecast] = control_loop.get_cached_solar_forecast(day)
        if forecast is None:
            with self._element:
                ui.label('loading solar forecast...').classes('text-center italic')
        else:
            self._render(forecast)

    def _update(self, solar_forecast: DailySolarForecast) -> None:
        # Recreate the solar forecast table
        self._element.clear()
        self._render(solar_forecast)

    def _render(self, solar_forecast: DailySolarForecast):
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
                ui.label(f'{total}{KILOWATT_HOURS}').classes('solar-number')

            # Forecast table
            with ui.column().classes('w-full gap-3'):
                with ui.element('div').classes('solar-table'):
                    with ui.element('div').classes('solar-row solar-header'):
                        ui.label('Time')
                        ui.label('Irradiance').classes('text-right')
                        ui.label('Temperature').classes('text-right')
                        ui.label('Power').classes('text-right')

                    forecast: SolarForecast
                    for i, forecast in enumerate(solar_forecast):
                        row_classes = 'solar-row'
                        if i % 2 == 1:
                            row_classes += ' solar-row-alt'

                        with ui.element('div').classes(row_classes):
                            ui.label(forecast.time.strftime('%H:%M')).classes('solar-time')
                            if forecast.irradiance > 0:
                                ui.label(f'{int(forecast.irradiance + 0.5)}').classes(f'solar-number')
                            else:
                                ui.label('.').classes(f'solar-number')
                            ui.label(f'{int(forecast.temperature + 0.5)}{CELSIUS}').classes(f'solar-number')
                            if forecast.power > 0:
                                ui.label(f'{forecast.power / 1000:.2f}{KILOWATTS}').classes('solar-number')
                            else:
                                ui.label('.').classes('solar-number')


def _json_page(name: str) -> ContentElement:
    """
    Prepare a page to show JSON data.

    Args:
        name: name of the page

    Returns:
        The content element to use for adding the rendered JSON data.
    """
    return _json_multi_page(name)[0]


def _json_multi_page(*names: str) -> List[ContentElement]:
    """
    Prepare a page to show multiple JSON data.
    """
    result: List[ContentElement] = []
    ui.add_head_html(_HEAD_HTML)
    with ui.element('div').classes('solala-page'):
        _page_header()

        with ui.column():
            for name in names:
                with ui.card():
                    ui.label(name).classes('text-h6')
                    registers_element = ui.code(language='nothing').classes('text-sm w-full grow')
                    result.append(registers_element)

    return result


def _page_header(ext: str = '', link: bool = True) -> None:
    """
    NiceGui snippet to add the Solala title to a page.
    Args:
        ext: A string to append to the title.
        link: Whether to create a link to the home page or not
    """
    with ui.element('div').classes('solala-header'):

        with ui.element('div').classes('solala-brand'):
            if link:
                with ui.link(target='/'):
                    ui.image('/images/solala.svg').classes('w-12 h-12 bg-transparent')
            else:
                ui.image('/images/solala.svg').classes('w-12 h-12 bg-transparent')

            with ui.element('div'):
                ui.label(f'{APP_NAME}{ext}').classes('solala-brand-name')
                ui.label(APP_SUBTITLE).classes('solala-brand-subtitle')


def _control_header(title: str) -> None:
    with ui.element('div').classes('control-header'):
        with ui.element('div').classes('control-title'):
            # ui.label(icon).classes('control-title-icon')
            ui.label(title)
        # with ui.element('div').classes('control-state'):
        #     ui.element('div').classes('control-state-dot')
        #     ui.label(state)


def _button_classes(button, primary=False, wide=False) -> None:
    classes = 'solala-button'
    if wide:
        classes += ' wide'
    button.classes(classes)
    if primary:
        button.props('color=primary')
    else:
        button.props('color=grey')
    return button


def _diagnostic_link(icon: str, name: str, target: str) -> None:
    with ui.link(target=target).classes('diagnostic-link'):
        ui.label(icon).classes('diagnostic-icon')
        ui.label(name)


def _ui_control_buttons() -> None:
    with ui.element('div').classes('control-column'):
        # ======================================================
        # BATTERY
        # ======================================================

        with ui.element('div').classes('dashboard-card control-card'):
            _control_header('Battery')
            with ui.element('div').classes('control-buttons'):
                battery_enable = ui.button('ENABLE').classes('solala-button')
                battery_disable = ui.button('DISABLE').classes('solala-button')
                battery_force_charge = ui.button('FORCE CHARGE').classes('solala-button')
                battery_force_discharge = ui.button('FORCE DISCHARGE').classes('solala-button')
                battery_cheap_force_discharge = ui.button('CHEAP ⇒ FORCE CHARGE').classes('solala-button')

                battery_force_charge.classes('wide')
                battery_force_discharge.classes('wide')
                battery_cheap_force_discharge.classes('wide')

            _register_listener(
                BatteryButtonUpdater(
                    battery_enable=battery_enable,
                    battery_disable=battery_disable,
                    battery_force_charge=battery_force_charge,
                    battery_force_discharge=battery_force_discharge,
                    battery_cheap_force_discharge=battery_cheap_force_discharge,
                )
            )

        # ======================================================
        # INVERTER
        # ======================================================

        with ui.element('div').classes('dashboard-card control-card'):
            _control_header('Inverter')
            with ui.element('div').classes('control-buttons'):
                inverter_enable = ui.button('ENABLE').classes('solala-button')
                inverter_disable = ui.button('DISABLE').classes('solala-button')
                inverter_zero_export = ui.button('ZERO EXPORT').classes('solala-button')
                inverter_neg_feed_in_zero_export = ui.button('NEG FEED-IN ⇒ ZERO EXPORT').classes(
                    'solala-button')

                inverter_zero_export.classes('wide')
                inverter_neg_feed_in_zero_export.classes('wide')

            _register_listener(
                InverterButtonUpdater(
                    inverter_enable=inverter_enable,
                    inverter_disable=inverter_disable,
                    inverter_zero_export=inverter_zero_export,
                    inverter_neg_feed_in_zero_export=inverter_neg_feed_in_zero_export,
                )
            )


def _infographic_click(element):
    click_id: Optional[str] = element.args
    if click_id == CLICK_ID_GRID:
        ui.navigate.to('/price_forecast_page')
    elif click_id == CLICK_ID_SUN:
        ui.navigate.to('/solar_forecast_page')
    elif click_id == CLICK_ID_INVERTER:
        pass
        # ui.notify('clicked inverter')
    elif click_id == CLICK_ID_HOME:
        pass
        # ui.notify('clicked home')
    elif click_id == CLICK_ID_BATTERY:
        pass
        # ui.notify('clicked the battery')


def _buy_price_class(price: float) -> str:
    if price >= BUY_PRICE_RED:
        return 'price-buy-high'
    elif price >= BUY_PRICE_AMBER:
        return 'price-buy-okay'
    else:
        return 'price-buy-good'


def _feed_in_price_class(price: float) -> str:
    if price >= 0:
        return 'price-feed-in-okay'
    else:
        return 'price-feed-in-bad'


# ====================================================================
#  Pages
# ====================================================================

# Mount static files
app.add_static_files(url_path='/images', local_directory=str(IMAGE_FILES))
app.add_static_files(url_path='/css', local_directory=str(CSS_FILES))
app.add_static_file(url_path='/manifest.json', local_file=str(RESOURCES / 'manifest.json'))


@ui.page('/')
def root_page():
    ui.add_head_html(_HEAD_HTML)
    with ui.element('div').classes('solala-page'):
        _page_header(link=False)

        with ui.element('div').classes('dashboard-grid'):
            # ----------------------------------------------------------
            # LIVE POWER INFOGRAPHIC
            # ----------------------------------------------------------
            with ui.element('div').classes('dashboard-card infographic-card'):
                ui.label('Power').classes('infographic-title')

                with ui.element('div').classes('infographic-container'):
                    infographic = ui.html()
                    infographic.on(
                        'click',
                        handler=_infographic_click,
                        js_handler="(e) => emit(e.target.closest('rect')?.id)",
                    )
                    _register_listener(
                        InfographicUpdater(
                            infographic_element=infographic
                        )
                    )

            # ----------------------------------------------------------
            # BATTERY + INVERTER control buttons
            # ----------------------------------------------------------
            _ui_control_buttons()

        # ==============================================================
        # DIAGNOSTICS
        # ==============================================================
        with ui.element('div').classes('dashboard-card diagnostics-card'):
            with ui.element('div').classes('diagnostics-title'):
                ui.label('Diagnostics')
            with ui.grid(columns=3):
                _diagnostic_link('?', 'Status', '/status_page')
                _diagnostic_link('⚙', 'Parameters', '/parameters_page')
                _diagnostic_link('↔', 'Connection', '/connection_page')
                _diagnostic_link('▤', 'Registers', '/registers_page')
                _diagnostic_link('▣', 'Log', '/log_page')
                _diagnostic_link('</>', 'API Schema', '/schema_page')


@ui.page('/price_forecast_page')
def price_forecast_page():
    ui.add_head_html(_HEAD_HTML)
    with ui.element('div').classes('solala-page price-forecast w-full max-w-5xl mx-auto p-4 md:p-6'):
        _page_header(' price forecast')
        element = ui.element('div')
        _register_listener(
            PriceForecastUpdater(
                element=element
            )
        )


@ui.page('/solar_forecast_page')
def solar_forecast_page():
    ui.add_head_html(_HEAD_HTML)
    today = date.today()

    swipe_area = ui.element('div').classes('w-full').style('touch-action: pan-y;')
    with swipe_area:
        with ui.element('div').classes('solala-page price-forecast w-full max-w-5xl mx-auto p-4 md:p-6'):
            _page_header(' solar forecast')

            # Navigation column
            with ui.column().classes(
                    'w-full items-start gap-1 p-2 mb-4 '
                    'rounded-xl bg-gray-50 dark:bg-gray-900'
            ):
                # Navigation row
                with ui.row().classes(
                        'w-full flex-nowrap items-center gap-1'
                ).style(
                    'justify-content: flex-start; '
                    'align-self: stretch; '
                    'margin-left: 0; margin-right: auto;'
                ):
                    button_classes = '!w-8 !h-8 min-w-0 shrink-0'
                    ui.button(
                        icon='chevron_left',
                        on_click=lambda: change_day(-1),
                    ).props('flat round color=grey').classes(button_classes).tooltip('Previous day')

                    with ui.column().classes('items-center gap-1 min-w-0'):
                        date_element = ui.label().classes(
                            'w-40 sm:w-64 shrink-0 text-center '
                            'text-xs sm:text-sm text-gray-500 whitespace-nowrap'
                        )
                        with ui.element('div').classes('h-7 flex items-center justify-center'):
                            day_status = ui.label('today').classes('text-xs sm:text-sm text-gray-500')
                            today_button = ui.button(
                                'back to today',
                                on_click=lambda: set_day(today),
                            ).props('flat dense no-caps color=primary').classes('text-xs sm:text-sm min-h-0 px-2 py-1')

                    ui.button(
                        icon='chevron_right',
                        on_click=lambda: change_day(1),
                    ).props('flat round color=grey').classes(button_classes).tooltip('Next day')

            # Forecast table will be rendered here
            forecast_element = ui.element('div').classes('w-full')

    # What follows is rendering and navigation

    # Handler for swipe actions
    def handle_swipe(event) -> None:
        direction = event.args
        if direction == 'left':
            change_day(1)
        elif direction == 'right':
            change_day(-1)

    swipe_area.on(
        'touchstart',
        js_handler="""(e) => {
            if (!e.changedTouches.length) return;

            const touch = e.changedTouches[0];
            e.currentTarget.dataset.startX = touch.clientX;
            e.currentTarget.dataset.startY = touch.clientY;
        }""",
    )

    swipe_area.on(
        'touchend',
        handle_swipe,
        js_handler="""(e) => {
            if (!e.changedTouches.length) return;

            const touch = e.changedTouches[0];
            const startX = Number(e.currentTarget.dataset.startX);
            const startY = Number(e.currentTarget.dataset.startY);

            // Ignore gestures if the starting position was not recorded.
            if (!Number.isFinite(startX) ||
                !Number.isFinite(startY)) return;

            const dx = touch.clientX - startX;
            const dy = touch.clientY - startY;

            // Require a deliberate horizontal swipe.
            if (Math.abs(dx) >= 60 &&
                Math.abs(dx) > Math.abs(dy) * 1.5) {
                emit(dx < 0 ? 'left' : 'right');
            }
        }""",
    )

    def handle_key(e: events.KeyEventArguments) -> None:
        if e.action.keydown:
            if e.key.arrow_left:
                change_day(-1)
            elif e.key.arrow_right:
                change_day(1)
            elif e.key.home:
                set_day(today)

    ui.keyboard(on_key=handle_key, repeating=False)

    updater = SolarForecastUpdater(element=forecast_element, day=today)
    _register_listener(updater)

    def set_day(day: date) -> None:
        updater.set_day(day)
        date_element.set_text(day.strftime('%A, %d %B %Y'))
        day_status.set_visibility(day == today)
        today_button.set_visibility(day != today)

    def change_day(offset: int) -> None:
        set_day(updater.day + timedelta(days=offset))

    set_day(today)


@ui.page('/status_page')
def status_page():
    """
    The old status page.
    """
    ui.add_head_html(_HEAD_HTML)
    with ui.element('div').classes('solala-page'):
        _page_header()
        with ui.element('div').classes('dashboard-grid'):
            # ----------------------------------------------------------
            # Status card
            # ----------------------------------------------------------
            with ui.card():
                ui.label('Status').classes('text-h6')
                _register_listener(StatusUpdater(
                    status_element=ui.code(language='nothing').classes('text-sm w-full grow')
                ))
            # ----------------------------------------------------------
            # BATTERY + INVERTER control buttons
            # ----------------------------------------------------------
            _ui_control_buttons()


@ui.page('/log_page')
def log_page():
    """
    Listen to the Solala logger and display log messages.
    """
    ui.add_head_html(_HEAD_HTML)
    with ui.element('div').classes('solala-page'):
        _page_header(' log console')
        log_ui = ui.log(max_lines=MAX_LOG_HISTORY).style('height: 100vh')
    ui.context.client.on_disconnect(partial(server_log.remove, log_ui))
    server_log.add(log_ui)


@ui.page('/registers_page')
def registers_page(match: Optional[str] = None):
    """
    Show the inverter registers.
    """
    json_element = _json_page('Registers')
    registers_elements = RegistersUpdater(registers_element=json_element, match=match)
    _register_listener(registers_elements)


@ui.page('/parameters_page')
def parameters_page():
    """
    Show the policy parameters and control constants.
    """
    policy_json = control_loop.get_policy_parameters()
    constants_json = control_loop.Constants.to_json()

    policy, consts = _json_multi_page('Policy', 'Constants')

    policy.set_content(
        render_json(policy_json, units=_PARAMETERS_UNITS)
    )

    consts.set_content(
        render_json(constants_json, remove_key_underscores=False, units=_CONSTANTS_UNITS)
    )


@ui.page('/connection_page')
def connection_page(match: Optional[str] = None):
    """
    Show the connection status.
    """
    connection_json = control_loop.get_connection_status()
    if match is not None:
        connection_json = filter_json(connection_json, match)

    _json_page('Connection').set_content(
        render_json(connection_json, float_format='.2f', units=_CONNECTION_UNITS)
    )


@ui.page('/schema_page')
async def schema_page():
    """
    Show the web API schema.
    """
    # Use Fast API to get the schema
    schema_json: JSONDict
    try:
        await ui.context.client.connected()
        schema_json = await ui.run_javascript('fetch("/schema").then(res => res.json())')
    except Exception as e:
        schema_json = {'error': str(e)}

    _json_page('API Schema').set_content(
        json.dumps(schema_json, indent=4)
    )
