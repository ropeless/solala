import asyncio
import logging
import threading
from abc import abstractmethod, ABC
from asyncio import AbstractEventLoop
from dataclasses import dataclass
from functools import partial
from typing import List, Mapping

from nicegui import ui, app
from nicegui.elements.button import Button
from nicegui.elements.mixins.content_element import ContentElement

from solala import control_loop
from solala.control_loop import BatteryPolicy, InverterPolicy, BatteryMode, InverterMode
from solala.log import SOLALA_LOG_FORMAT, LOGGER
from solala.resources import IMAGE_FILES
from solala.server_constants import APP_NAME
from solala.utils.dict_extras import dict_merge
from solala.utils.json import JSONDict, json_dict, render_json

_H1_class = 'text-h5'
_H2_class = 'text-h6'

# Units for pretty printing status
_PRICE = ' cents/kWh'
_WATTS = ' Watts'
_SECONDS = ' seconds'
_MINUTES = ' minutes'
_PCT = '%'
_PARAMETERS_UNITS: Mapping[str, str] = {
    'start_charge_price_threshold': _PRICE,
    'stop_charge_price_threshold': _PRICE,
    'disable_export_price_threshold': _PRICE,
    'enable_export_price_threshold': _PRICE,
}
_STATUS_UNITS: Mapping[str, str] = dict_merge(
    {
        'buy_price': _PRICE,
        'feed_in_price': _PRICE,
        'renewables': _PCT,
        'state_of_charge': _PCT,
        'power_limit': _PCT,
        'grid_power': _WATTS,
        'solar_power': _WATTS,
        'battery_power': _WATTS,
        'house_power': _WATTS,
    },
    _PARAMETERS_UNITS,
)
_CONSTANTS_UNITS: Mapping[str, str] = {
    "LOOP_SLEEP": _SECONDS,
    "CONTROL_DURATION": _SECONDS,
    "PRICE_LOOK_AHEAD": _MINUTES,
    "DISABLE_FEED_IN_TOLERANCE": _PRICE,
    "ENABLE_FEED_IN_TOLERANCE": _PRICE,
    "STOP_BUY_TOLERANCE": _PRICE,
    "START_BUY_TOLERANCE": _PRICE,
}


class NiceGuiLogHandler(logging.Handler):
    """
    A custom logging Handler that writes the Solala logger
    to NiceGUI ui.log components.
    """

    def __init__(self):
        super().__init__()
        self._log_elements: List[ui.log] = []
        self.setFormatter(logging.Formatter(SOLALA_LOG_FORMAT))
        LOGGER.addHandler(self)

    def emit(self, record):
        try:
            # Format the log message using the handler's formatter
            msg = self.format(record)
            # Push the message to the NiceGUI UI element
            for ui_log in self._log_elements:
                ui_log.push(msg)
        except (IOError, ValueError, RuntimeError):
            self.handleError(record)

    def add(self, element: ui.log) -> None:
        self.remove(element)
        self._log_elements.append(element)

    def remove(self, element: ui.log) -> None:
        try:
            self._log_elements.remove(element)
        except ValueError:
            pass


_LOG_HANDLER = NiceGuiLogHandler()


@dataclass
class StatusListener(ABC):

    def __post_init__(self):
        self._main_loop: AbstractEventLoop = asyncio.get_running_loop()

    def update(self, status_json: JSONDict) -> None:
        """
        Thread safe update.
        """
        self._main_loop.call_soon_threadsafe(partial(self._update, status_json))

    def update_now(self) -> None:
        """
        Thread _unsafe_ update.
        """
        status_json: JSONDict = control_loop.get_status()
        self._update(status_json)

    @abstractmethod
    def _update(self, status_json: JSONDict) -> None:
        ...


class StatusHandler(control_loop.ControlLoopListener):
    def __init__(self):
        self._lock = threading.Lock()
        self._handlers: list[StatusListener] = []
        control_loop.add_listener(self)

    def __del__(self):
        control_loop.remove_listener(self)

    def update(self) -> None:
        with self._lock:
            if len(self._handlers) > 0:
                status_json: JSONDict = control_loop.get_status()
                for listener in self._handlers:
                    listener.update(status_json)

    def add(self, handler: StatusListener) -> None:
        with self._lock:
            try:
                self._handlers.remove(handler)
            except ValueError:
                pass
        self._handlers.append(handler)

    def remove(self, handler: StatusListener) -> None:
        with self._lock:
            try:
                self._handlers.remove(handler)
            except ValueError:
                pass


_STATUS_HANDLER = StatusHandler()


@dataclass
class RegistersListener:

    def __post_init__(self):
        self._main_loop: AbstractEventLoop = asyncio.get_running_loop()

    def update(self, registers_json: JSONDict) -> None:
        """
        Thread safe update.
        """
        self._main_loop.call_soon_threadsafe(partial(self._update, registers_json))

    def update_now(self) -> None:
        """
        Thread _unsafe_ update.
        """
        registers_json: JSONDict = control_loop.get_registers()
        self._update(registers_json)

    def _update(self, registers_json: JSONDict) -> None:
        ...


class RegistersHandler(control_loop.ControlLoopListener):
    def __init__(self):
        self._lock = threading.Lock()
        self._handlers: list[RegistersListener] = []
        control_loop.add_listener(self)

    def __del__(self):
        control_loop.remove_listener(self)

    def update(self) -> None:
        with self._lock:
            if len(self._handlers) > 0:
                registers_json: JSONDict = control_loop.get_registers()
                for listener in self._handlers:
                    listener.update(registers_json)

    def add(self, handler: RegistersListener) -> None:
        with self._lock:
            try:
                self._handlers.remove(handler)
            except ValueError:
                pass
        self._handlers.append(handler)

    def remove(self, handler: RegistersListener) -> None:
        with self._lock:
            try:
                self._handlers.remove(handler)
            except ValueError:
                pass


_REGISTERS_HANDLER = RegistersHandler()


def handle_battery_enable():
    control_loop.set_control(
        battery_mode=BatteryMode.ENABLE,
        battery_policy=BatteryPolicy.MANUAL,
    )
    _STATUS_HANDLER.update()


def handle_battery_disable():
    control_loop.set_control(
        battery_mode=BatteryMode.DISABLE,
        battery_policy=BatteryPolicy.MANUAL,
    )
    _STATUS_HANDLER.update()


def handle_battery_force_charge():
    control_loop.set_control(
        battery_mode=BatteryMode.FORCE_CHARGE,
        battery_policy=BatteryPolicy.MANUAL,
    )
    _STATUS_HANDLER.update()


def handle_battery_force_discharge():
    control_loop.set_control(
        battery_mode=BatteryMode.FORCE_DISCHARGE,
        battery_policy=BatteryPolicy.MANUAL,
    )
    _STATUS_HANDLER.update()


def handle_battery_cheap_force_discharge():
    control_loop.set_control(
        battery_policy=BatteryPolicy.CHEAP_CHARGE,
    )
    _STATUS_HANDLER.update()


def handle_inverter_enable():
    control_loop.set_control(
        inverter_mode=InverterMode.ENABLE,
        inverter_policy=InverterPolicy.MANUAL,
    )
    _STATUS_HANDLER.update()


def handle_inverter_disable():
    control_loop.set_control(
        inverter_mode=InverterMode.DISABLE,
        inverter_policy=InverterPolicy.MANUAL,
    )
    _STATUS_HANDLER.update()


def handle_inverter_zero_export():
    control_loop.set_control(
        inverter_mode=InverterMode.ZERO_EXPORT,
        inverter_policy=InverterPolicy.MANUAL,
    )
    _STATUS_HANDLER.update()


def handle_inverter_neg_feed_in_zero_export():
    control_loop.set_control(
        inverter_policy=InverterPolicy.NEG_FEED_IN_ZERO_EXPORT,
    )
    _STATUS_HANDLER.update()


@dataclass
class StatusElements(StatusListener):
    status_element: ContentElement
    battery_enable: Button
    battery_disable: Button
    battery_force_charge: Button
    battery_force_discharge: Button
    battery_cheap_force_discharge: Button
    inverter_enable: Button
    inverter_disable: Button
    inverter_zero_export: Button
    inverter_neg_feed_in_zero_export: Button

    def _update(self, status_json: JSONDict) -> None:
        try:
            control_json: JSONDict = json_dict(status_json['control'])
            battery_status: JSONDict = json_dict(control_json['battery'])
            inverter_status: JSONDict = json_dict(control_json['inverter'])

            battery_mode = battery_status['mode']
            battery_policy = battery_status['policy']
            battery_button = (
                battery_policy
                if battery_policy != BatteryPolicy.MANUAL.name
                else battery_mode
            )
            inverter_mode = inverter_status['mode']
            inverter_policy = inverter_status['policy']
            inverter_button = (
                inverter_policy
                if inverter_policy != InverterPolicy.MANUAL.name
                else inverter_mode
            )

        except (KeyError, TypeError, IOError, control_loop.ControlLoopError) as err:
            LOGGER.error(f'Error getting control status: {err}')
            battery_button = ''
            inverter_button = ''
        json_str = render_json(status_json, float_format='.2f', units=_STATUS_UNITS)

        self.status_element.set_content(json_str)

        def on_props(_on: bool) -> str:
            return 'color=blue dense' if _on else 'color=grey dense'

        # Set all buttons off
        self.battery_enable.props(on_props(battery_button == 'ENABLE'))
        self.battery_disable.props(on_props(battery_button == 'DISABLE'))
        self.battery_force_charge.props(on_props(battery_button == 'FORCE_CHARGE'))
        self.battery_force_discharge.props(on_props(battery_button == 'FORCE_DISCHARGE'))
        self.battery_cheap_force_discharge.props(on_props(battery_button == 'CHEAP_FORCE_DISCHARGE'))
        self.inverter_enable.props(on_props(inverter_button == 'ENABLE'))
        self.inverter_disable.props(on_props(inverter_button == 'DISABLE'))
        self.inverter_zero_export.props(on_props(inverter_button == 'ZERO_EXPORT'))
        self.inverter_neg_feed_in_zero_export.props(on_props(inverter_button == 'NEG_FEED_IN_ZERO_EXPORT'))


@dataclass
class RegistersElement(RegistersListener):
    registers_element: ContentElement

    def _update(self, registers_json: JSONDict) -> None:
        json_str = render_json(
            registers_json,
            float_format='.2f',
            remove_key_underscores=False,
            remove_value_underscores=False,
        )
        self.registers_element.set_content(json_str)


def _json_page(name: str) -> ContentElement:
    with ui.column().style('width: 100vw; height: 100vh'):
        _title()
        with ui.card():
            ui.label(name).classes(_H2_class)
            registers_element = ui.code(language='nothing').classes('text-sm w-full grow')
    return registers_element


def _favicon() -> None:
    ui.add_head_html('''
        <link rel="icon" type="image/png" sizes="16x16" href="/images/solala-16x16.png">
        <link rel="icon" type="image/png" sizes="32x32" href="/images/solala-32x32.png">
    ''')


def _title(ext: str = '', link: bool = True) -> None:
    with ui.row().classes('items-center gap-4'):
        if link:
            with ui.link(target='/'):
                image = ui.image('/images/solala.svg')
        else:
            image = ui.image('/images/solala.svg')
        image.classes('w-12 h-12 obj-contain')
        ui.label(f'{APP_NAME}{ext}').classes(_H1_class)


# ====================================================================
#  Pages
# ====================================================================

# Mount static directories
app.add_static_files(url_path='/images', local_directory=str(IMAGE_FILES))


@ui.page('/')
@ui.page('/status_page')
def status_page():
    """
    The main status page.
    """
    _favicon()
    with ui.column().style('width: 100vw; height: 100vh'):
        _title(link=False)
        with ui.card():
            ui.label('Status').classes(_H2_class)
            status_element = ui.code(language='nothing').classes('text-sm w-full grow')
            with ui.row():
                ui.link('Registers', '/registers_page')
                ui.link('Parameters', '/parameters_page')
                ui.link('Connection', '/connection_page')
                ui.link('Constants', '/constants_page')
                ui.link('Log', '/log_page')
        with ui.card():
            ui.label('Battery').classes(_H2_class)
            with ui.row():
                battery_enable = ui.button('enable', on_click=handle_battery_enable)
                battery_disable = ui.button('disable', on_click=handle_battery_disable)
                battery_force_charge = ui.button('force charge', on_click=handle_battery_force_charge)
                battery_force_discharge = ui.button('force discharge', on_click=handle_battery_force_discharge)
                battery_cheap_force_discharge = \
                    ui.button('cheap ⇒ force charge', on_click=handle_battery_cheap_force_discharge)
        with ui.card():
            ui.label('Inverter').classes(_H2_class)
            with ui.row():
                inverter_enable = ui.button('enable', on_click=handle_inverter_enable)
                inverter_disable = ui.button('disable', on_click=handle_inverter_disable)
                inverter_zero_export = ui.button('zero export', on_click=handle_inverter_zero_export)
                inverter_neg_feed_in_zero_export = \
                    ui.button('neg feed-in ⇒ zero export', on_click=handle_inverter_neg_feed_in_zero_export)

    status_elements = StatusElements(
        status_element=status_element,
        battery_enable=battery_enable,
        battery_disable=battery_disable,
        battery_force_charge=battery_force_charge,
        battery_force_discharge=battery_force_discharge,
        battery_cheap_force_discharge=battery_cheap_force_discharge,
        inverter_enable=inverter_enable,
        inverter_disable=inverter_disable,
        inverter_zero_export=inverter_zero_export,
        inverter_neg_feed_in_zero_export=inverter_neg_feed_in_zero_export,
    )
    status_elements.update_now()
    ui.context.client.on_disconnect(lambda: _STATUS_HANDLER.remove(status_elements))
    _STATUS_HANDLER.add(status_elements)


@ui.page('/log_page')
def log_page():
    """
    Listen to the Solala logger and display log messages.
    """
    _favicon()
    with ui.column().style('width: 100vw; height: 100vh'):
        _title(' log console')
        log_ui = ui.log(max_lines=None).classes(
            'w-full grow min-h-0 text-mono text-body2 p-2 overflow-auto'
        )
        ui.context.client.on_disconnect(lambda: _LOG_HANDLER.remove(log_ui))
        _LOG_HANDLER.add(log_ui)


@ui.page('/registers_page')
def registers_page():
    """
    Show the inverter registers.
    """
    _favicon()
    json_element = _json_page('Registers')
    registers_elements = RegistersElement(registers_element=json_element)
    registers_elements.update_now()
    ui.context.client.on_disconnect(lambda: _REGISTERS_HANDLER.remove(registers_elements))
    _REGISTERS_HANDLER.add(registers_elements)


@ui.page('/parameters_page')
def parameters_page():
    """
    Show the policy parameters.
    """
    _favicon()
    json_element = _json_page('Parameters')
    json_element.set_content(
        render_json(
            control_loop.get_parameters(),
            units=_PARAMETERS_UNITS,
        )
    )


@ui.page('/constants_page')
def constants_page():
    """
    Show the control loop constants.
    """
    _favicon()
    json_element = _json_page('Constants')
    json_element.set_content(
        render_json(
            control_loop.Constants.as_dict(),
            units=_CONSTANTS_UNITS,
        )
    )


@ui.page('/connection_page')
def connection_page():
    """
    Show the connection status.
    """
    _favicon()
    json_element = _json_page('Connection')
    json_element.set_content(
        render_json(
            control_loop.get_connection_status(),
            units=_CONSTANTS_UNITS,
        )
    )
