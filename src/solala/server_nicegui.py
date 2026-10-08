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
from solala.resources import IMAGE_FILES, RESOURCES
from solala.server_constants import APP_NAME, MAX_LOG_HISTORY, APP_SUBTITLE
from solala.server_constants import LOGGER
from solala.server_infographic import Infographic
from solala.units import PRICE, PERCENT, WATTS, VOLTS, AMPS, SECONDS, MINUTES
from solala.utils.dict_extras import dict_merge
from solala.utils.json import JSONDict, json_dict, render_json, filter_json, json_str

# --------------------------------------------------------------------
# Main styling
# --------------------------------------------------------------------

_H1_class = 'text-h5'
_H2_class = 'text-h6'

_HEAD_HTML = r'''
<link rel="manifest" href="/manifest.json">
<link rel="apple-touch-icon" href="/images/apple-touch-icon.png?v=6">
<style>
    /* ---------- Page ---------- */
    .solala-page {
        width: 100%;
        max-width: 1400px;
        margin: 0 auto;
        padding: 16px;
        background: #f5f7f9;
    }
    /* ---------- Header ---------- */
    .solala-header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        margin-bottom: 16px;
    }
    .solala-brand {
        display: flex;
        align-items: center;
        gap: 10px;
    }
    .solala-brand img {
        width: 42px;
        height: 42px;
    }
    .solala-brand-name {
        font-size: 24px;
        font-weight: 650;
        line-height: 1.1;
    }
    .solala-brand-subtitle {
        font-size: 12px;
        color: #687078;
    }
    .system-status {
        display: flex;
        align-items: center;
        gap: 7px;
        font-size: 13px;
        font-weight: 600;
    }
    .system-status-dot {
        width: 9px;
        height: 9px;
        border-radius: 50%;
        background: #16a34a;
    }
    /* ---------- Main grid ---------- */
    .dashboard-grid {
        display: grid;
        grid-template-columns: minmax(0, 1.6fr) minmax(330px, 0.85fr);
        gap: 16px;
        align-items: start;
    }
    /* ---------- Cards ---------- */
    .dashboard-card {
        background: white;
        border: 1px solid #e1e6ea;
        border-radius: 14px;
        box-shadow: 0 2px 7px rgba(0,0,0,.06);
    }
    /* ---------- Infographic ---------- */
    .infographic-card {
        padding: 12px;
    }
    .infographic-title {
        font-size: 18px;
        font-weight: 650;
        padding: 4px 8px 10px;
    }
    .infographic-container {
        width: 100%;
        display: flex;
        justify-content: center;
        align-items: center;
    }
    .infographic-container svg {
        width: 100%;
        height: auto;
        max-width: 760px;
    }
    /* ---------- Controls ---------- */
    .control-column {
        display: flex;
        flex-direction: column;
        gap: 16px;
    }
    .control-card {
        padding: 16px;
    }
    .control-header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        margin-bottom: 13px;
    }
    .control-title {
        display: flex;
        align-items: center;
        gap: 9px;
        font-size: 20px;
        font-weight: 650;
    }
    .control-title-icon {
        font-size: 24px;
    }
    .control-state {
        display: inline-flex;
        align-items: center;
        gap: 5px;
        padding: 4px 9px;
        border-radius: 14px;
        background: #e8f6eb;
        color: #087a0b;
        font-size: 12px;
        font-weight: 600;
    }
    .control-state-dot {
        width: 7px;
        height: 7px;
        border-radius: 50%;
        background: #16a34a;
    }
    .control-buttons {
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 8px;
    }
    .control-buttons .wide {
        grid-column: 1 / -1;
    }
    /* ---------- NiceGUI buttons ---------- */
    .solala-button {
        min-height: 42px;
        border-radius: 7px;
        font-size: 13px;
        font-weight: 600;
    }
    /* ---------- Diagnostics ---------- */
    .diagnostics-card {
        margin-top: 16px;
        padding: 16px;
    }
    .diagnostics-title {
        display: flex;
        align-items: center;
        gap: 8px;
        font-size: 18px;
        font-weight: 650;
        margin-bottom: 12px;
    }
    .diagnostic-grid {
        display: grid;
        grid-template-columns: repeat(4, 1fr);
        gap: 8px;
    }
    .diagnostic-link {
        min-height: 60px;
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        gap: 3px;

        border: 1px solid #e0e6eb;
        border-radius: 8px;
        background: #f5f7f9;

        color: #1976d2;
        text-decoration: none;
        font-size: 12px;
        font-weight: 600;
    }
    .diagnostic-link:hover {
        background: #eaf3fb;
        border-color: #90caf9;
    }
    .diagnostic-icon {
        font-size: 18px;
    }
    /* ---------- Tablet ---------- */
    @media (max-width: 900px) {
        .dashboard-grid {
            grid-template-columns: 1fr;
        }
        .control-column {
            display: grid;
            grid-template-columns: 1fr 1fr;
        }
        .diagnostics-card {
            margin-top: 16px;
        }
    }
    /* ---------- Phone ---------- */
    @media (max-width: 600px) {
        .solala-page {
            padding: 8px;
        }
        .solala-header {
            margin-bottom: 9px;
        }
        .solala-brand img {
            width: 35px;
            height: 35px;
        }
        .solala-brand-name {
            font-size: 20px;
        }
        .solala-brand-subtitle {
            display: none;
        }
        .system-status {
            font-size: 11px;
        }
        .dashboard-grid {
            gap: 9px;
        }
        .infographic-card {
            padding: 7px;
        }
        .infographic-title {
            font-size: 18px;
            padding: 3px 5px 6px;
        }
        .control-column {
            display: flex;
            gap: 9px;
        }
        .control-card {
            padding: 12px;
        }
        .control-title {
            font-size: 18px;
        }
        .control-buttons {
            gap: 7px;
        }
        .solala-button {
            min-height: 43px;
            font-size: 12px;
        }
        .diagnostics-card {
            margin-top: 9px;
            padding: 12px;
        }
        .diagnostic-grid {
            grid-template-columns: repeat(3, 1fr);
        }
        .diagnostic-link {
            min-height: 55px;
            font-size: 11px;
        }
    }
</style>
'''

# Units for pretty printing status
_PARAMETERS_UNITS: Mapping[str, str] = {
    'start_charge_price_threshold': PRICE,
    'stop_charge_price_threshold': PRICE,
    'disable_export_price_threshold': PRICE,
    'enable_export_price_threshold': PRICE,
}
_STATUS_UNITS: Mapping[str, str] = dict_merge(
    {
        'buy_price': PRICE,
        'feed_in_price': PRICE,
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
    'DISABLE_FEED_IN_TOLERANCE': PRICE,
    'ENABLE_FEED_IN_TOLERANCE': PRICE,
    'STOP_BUY_TOLERANCE': PRICE,
    'START_BUY_TOLERANCE': PRICE,
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
    ui.add_head_html(_HEAD_HTML)
    with ui.element('div').classes('solala-page'):
        _page_header()

        with ui.element('div').classes('dashboard-grid'):
            with ui.card():
                ui.label(name).classes(_H2_class)
                registers_element = ui.code(language='nothing').classes('text-sm w-full grow')
    return registers_element


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
                    ui.label(name).classes(_H2_class)
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


# ====================================================================
#  Pages
# ====================================================================

# Mount static directories
app.add_static_files(url_path='/images', local_directory=str(IMAGE_FILES))
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
                _diagnostic_link('🛈', 'Status', '/status_page')
                _diagnostic_link('⚙', 'Parameters', '/parameters_page')
                _diagnostic_link('↔', 'Connection', '/connection_page')
                _diagnostic_link('▤', 'Registers', '/registers_page')
                _diagnostic_link('▣', 'Log', '/log_page')
                _diagnostic_link('⬡', 'API Schema', '/schema_page')


@ui.page('/status_page')
def status_page():
    """
    The main status page.
    """
    ui.add_head_html(_HEAD_HTML)
    with ui.element('div').classes('solala-page'):
        _page_header()
        with ui.element('div').classes('dashboard-grid'):
            # ----------------------------------------------------------
            # Status card
            # ----------------------------------------------------------
            with ui.card():
                ui.label('Status').classes(_H2_class)
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
