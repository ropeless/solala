import asyncio
import logging
from abc import abstractmethod
from asyncio import AbstractEventLoop
from functools import partial
from typing import List, Mapping, final, Optional, Dict

from nicegui import ui, app
from nicegui.elements.button import Button
from nicegui.elements.mixins.content_element import ContentElement

from solala import control_loop
from solala.control_loop import listeners as control_loop_listeners, BatteryMode, BatteryPolicy, InverterMode, \
    InverterPolicy
from solala.resources import IMAGE_FILES
from solala.server_constants import APP_NAME
from solala.server_constants import SOLALA_LOG_FORMAT, LOGGER
from solala.server_infographic import Infographic
from solala.units import PRICE, PERCENT, WATTS, VOLTS, AMPS, SECONDS, MINUTES
from solala.utils.dict_extras import dict_merge
from solala.utils.json import JSONDict, json_dict, render_json, filter_json, json_str

_H1_class = 'text-h5'
_H2_class = 'text-h6'

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
    with ui.column().style('width: 100vw; height: 100vh'):
        _title()
        with ui.card():
            ui.label(name).classes(_H2_class)
            registers_element = ui.code(language='nothing').classes('text-sm w-full grow')
    return registers_element


def _title(ext: str = '', link: bool = True) -> None:
    """
    NiceGui snippet to add the Solala title to a page.
    Args:
        ext: A string to append to the title.
        link: Whether to create a link to the home page or not
    """
    with ui.row().classes('items-center gap-4'):
        if link:
            with ui.link(target='/'):
                image = ui.image('/images/solala.svg')
        else:
            image = ui.image('/images/solala.svg')
        image.classes('w-12 h-12 bg-transparent')
        ui.label(f'{APP_NAME}{ext}').classes(_H1_class)


# ====================================================================
#  Pages
# ====================================================================

# Mount static directories
app.add_static_files(url_path='/images', local_directory=str(IMAGE_FILES))


@ui.page('/')
def root_page():
    with ui.column().style('width: 100vw; height: 100vh'):
        _register_listener(
            InfographicUpdater(
                infographic_element=ui.html(),
            )
        )
        with ui.card():
            ui.label('Battery').classes(_H2_class)
            with ui.row():
                _register_listener(BatteryButtonUpdater(
                    battery_enable=ui.button('enable'),
                    battery_disable=ui.button('disable'),
                    battery_force_charge=ui.button('force charge'),
                    battery_force_discharge=ui.button('force discharge'),
                    battery_cheap_force_discharge=ui.button('cheap ⇒ force charge'),
                ))
        with ui.card():
            ui.label('Inverter').classes(_H2_class)
            with ui.row():
                _register_listener(InverterButtonUpdater(
                    inverter_enable=ui.button('enable'),
                    inverter_disable=ui.button('disable'),
                    inverter_zero_export=ui.button('zero export'),
                    inverter_neg_feed_in_zero_export=ui.button('neg feed-in ⇒ zero export'),
                ))
        with ui.card():
            ui.label('Links').classes(_H2_class)
            with ui.row():
                ui.link('Status', '/status_page')
                ui.link('Parameters', '/parameters_page')
                ui.link('Connection', '/connection_page')
                ui.link('Registers', '/registers_page')
                ui.link('Constants', '/constants_page')
                ui.link('Log', '/log_page')
                ui.link('API Schema', '/schema')


@ui.page('/status_page')
def status_page():
    """
    The main status page.
    """
    with ui.column().style('width: 100vw; height: 100vh'):
        _title()
        with ui.card():
            ui.label('Status').classes(_H2_class)
            _register_listener(StatusUpdater(
                status_element=ui.code(language='nothing').classes('text-sm w-full grow')
            ))
        with ui.card():
            ui.label('Battery').classes(_H2_class)
            with ui.row():
                _register_listener(BatteryButtonUpdater(
                    battery_enable=ui.button('enable'),
                    battery_disable=ui.button('disable'),
                    battery_force_charge=ui.button('force charge'),
                    battery_force_discharge=ui.button('force discharge'),
                    battery_cheap_force_discharge=ui.button('cheap ⇒ force charge'),
                ))
        with ui.card():
            ui.label('Inverter').classes(_H2_class)
            with ui.row():
                _register_listener(InverterButtonUpdater(
                    inverter_enable=ui.button('enable'),
                    inverter_disable=ui.button('disable'),
                    inverter_zero_export=ui.button('zero export'),
                    inverter_neg_feed_in_zero_export=ui.button('neg feed-in ⇒ zero export'),
                ))


@ui.page('/log_page')
def log_page():
    """
    Listen to the Solala logger and display log messages.
    """
    with ui.column().style('width: 100vw; height: 100vh'):
        _title(' log console')
        log_ui = ui.log(max_lines=None).classes(
            'w-full grow min-h-0 text-mono text-body2 p-2 overflow-auto'
        )
    ui.context.client.on_disconnect(partial(_LOG_HANDLER.remove, log_ui))
    _LOG_HANDLER.add(log_ui)


@ui.page('/registers_page')
def registers_page(match: Optional[str] = None):
    """
    Show the inverter registers.
    """
    json_element = _json_page('Registers')
    registers_elements = RegistersUpdater(registers_element=json_element, match=match)
    _register_listener(registers_elements)


@ui.page('/parameters_page')
def parameters_page(match: Optional[str] = None):
    """
    Show the policy parameters.
    """
    parameters_json = control_loop.get_parameters()
    if match is not None:
        parameters_json = filter_json(parameters_json, match)

    _json_page('Parameters').set_content(
        render_json(parameters_json, units=_PARAMETERS_UNITS)
    )


@ui.page('/constants_page')
def constants_page(match: Optional[str] = None):
    """
    Show the control loop constants.
    """
    constants_json = control_loop.Constants.as_dict()
    if match is not None:
        constants_json = filter_json(constants_json, match)

    _json_page('Constants').set_content(
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
