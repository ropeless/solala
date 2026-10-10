import asyncio
import json
from abc import abstractmethod
from asyncio import AbstractEventLoop
from functools import partial
from typing import Mapping, final, Optional, Dict, List

from nicegui import ui, app
from nicegui.elements.button import Button
from nicegui.elements.mixins.content_element import ContentElement

from solala import control_loop, server_log
from solala.control_loop import listeners as control_loop_listeners, BatteryMode, BatteryPolicy, InverterMode, \
    InverterPolicy
from solala.power_pricer.power_pricer import Price
from solala.resources import IMAGE_FILES, RESOURCES, CSS_FILES
from solala.server_constants import APP_NAME, MAX_LOG_HISTORY, APP_SUBTITLE, BUY_PRICE_RED, BUY_PRICE_AMBER
from solala.server_constants import LOGGER
from solala.server_infographic import Infographic, CLICK_ID_HOME, CLICK_ID_SUN, CLICK_ID_GRID, CLICK_ID_BATTERY, \
    CLICK_ID_INVERTER
from solala.units import PRICE_CENTS, PERCENT, WATTS, VOLTS, AMPS, SECONDS, MINUTES, HOURS
from solala.utils.dict_extras import dict_merge
from solala.utils.json import JSONDict, json_dict, render_json, filter_json, json_str

# --------------------------------------------------------------------
# Main styling
# --------------------------------------------------------------------

_HEAD_HTML = r'''
<link rel="manifest" href="/manifest.json">
<link rel="stylesheet" href="/css/solala.css">
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
        'power': WATTS,
        'voltage': VOLTS,
        'current': AMPS,
    },
    _PARAMETERS_UNITS,
)
_CONSTANTS_UNITS: Mapping[str, str] = {
    'LOOP_TIME': SECONDS,
    'MIN_SLEEP_TIME': SECONDS,
    'CONTROL_DURATION': SECONDS,
    'PRICE_LOOK_AHEAD': MINUTES,
    'PRICE_SETTLE_CHECK': SECONDS,
    'PRICE_FORECAST_DURATION': HOURS,
}


class StatusListener(control_loop_listeners.StatusListener):

    def __init__(self):
        super().__init__()
        self._main_loop: AbstractEventLoop = asyncio.get_running_loop()

    @final
    def update(self, status_json: JSONDict) -> None:
        """
        Thread safe update.
        """
        self._main_loop.call_soon_threadsafe(partial(self._update, status_json))

    @abstractmethod
    def _update(self, status_json: JSONDict) -> None:
        ...


class RegistersListener(control_loop_listeners.RegistersListener):

    def __init__(self):
        super().__init__()
        self._main_loop: AbstractEventLoop = asyncio.get_running_loop()

    @final
    def update(self, register_values: Dict[str, int | float | str | bool]) -> None:
        """
        Thread safe update.
        """
        self._main_loop.call_soon_threadsafe(partial(self._update, register_values))

    def _update(self, registers_json: JSONDict) -> None:
        ...


def _register_listener(listener: StatusListener | RegistersListener) -> None:
    listener.update_now()
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
    elif click_id == CLICK_ID_INVERTER:
        pass
        # ui.notify('clicked inverter')
    elif click_id == CLICK_ID_HOME:
        pass
        # ui.notify('clicked home')
    elif click_id == CLICK_ID_SUN:
        pass
        # ui.notify('clicked the sun')
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
                _diagnostic_link('�', 'Status', '/status_page')
                _diagnostic_link('⚙', 'Parameters', '/parameters_page')
                _diagnostic_link('↔', 'Connection', '/connection_page')
                _diagnostic_link('▤', 'Registers', '/registers_page')
                _diagnostic_link('🗎', 'Log', '/log_page')
                _diagnostic_link('</>', 'API Schema', '/schema_page')


@ui.page('/price_forecast_page')
def price_forecast_page():
    prices: List[Price] = control_loop.get_forecast_prices()

    ui.add_head_html(_HEAD_HTML)
    with ui.element('div').classes('solala-page price-forecast w-full max-w-5xl mx-auto p-4 md:p-6'):
        _page_header(' price forecast')

        if len(prices) == 0:
            with ui.card().classes('w-full bg-white rounded-xl border border-[#e1e6ea] p-6'):
                ui.icon('query_stats').classes('text-3xl text-[#a1a9ae]')
                ui.label('No price forecast available').classes('text-lg font-semibold')
                ui.label('There are currently no forecast prices to display.').classes('text-sm text-gray-500')
            return

        forecast_date = prices[0].start_time.date()

        with ui.row().classes('items-center gap-2 mb-5'):
            ui.icon('calendar_today').classes('text-lg text-gray-500')
            ui.label(forecast_date.strftime('%A, %d %B %Y')).classes('text-sm text-gray-500')

        # Forecast table
        with ui.column().classes('w-full gap-3'):
            with ui.element('div').classes('price-table'):
                with ui.element('div').classes('price-row price-header'):
                    ui.label('Time')
                    ui.label('Buy price').classes('text-right')
                    ui.label('Feed-in').classes('text-right')

                for i, price in enumerate(prices):
                    row_classes = 'price-row'
                    if i % 2 == 1:
                        row_classes += ' price-row-alt'

                    with ui.element('div').classes(row_classes):
                        ui.label(price.start_time.strftime('%H:%M')).classes('price-time')

                        buy_class = _buy_price_class(price.buy_price)
                        ui.label(f'{price.buy_price:.1f}').classes(f'price-number {buy_class}')

                        feed_class = _feed_in_price_class(price.feed_in_price)
                        ui.label(f'{price.feed_in_price:.1f}').classes(f'price-number {feed_class}')


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
    parameters_json = control_loop.get_parameters()
    constants_json = control_loop.Constants.as_dict()

    params, consts = _json_multi_page('Parameters', 'Constants')

    params.set_content(
        render_json(parameters_json, units=_PARAMETERS_UNITS)
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
        render_json(connection_json)
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
