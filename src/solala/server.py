import json
import re
import threading
from typing import List, Optional, Dict

import uvicorn
from fastapi import FastAPI, Request, status
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from jinja2 import FunctionLoader, select_autoescape, Environment

from solala import control_loop
from solala.control_loop import BatteryMode, InverterMode, BatteryPolicy, InverterPolicy
from solala.log import LOGGER
from solala.resources import HTML_FILES
from solala.settings import Settings
from solala.utils.json import JSONDict, json_dict, JSONValue

_APP_NAME: str = 'Solala'
_REFRESH_INTERVAL = control_loop.Constants.LOOP_SLEEP
_DEFAULT_SETTINGS = Settings()

_ADDRESS_DELIMITERS_PATTERN = re.compile(r'[,;&\s]+')
_LINE_ENDINGS_PATTERN = re.compile(r'[,{} \t]*\s*(?=\n|$)')
_BLANK_LINES_PATTERN = re.compile(r'^[ \t]*\r?\n', flags=re.MULTILINE)
_DICT_ENTRY_SEPARATOR_PATTERN = re.compile(r'(\s*[\w+"]): ')

# Units for pretty printing status
_PRICE = ' cents/kWh'
_WATTS = ' Watts'
_PCT = '%'
_STATUS_UNITS = {
    'buy_price': _PRICE,
    'feed_in_price': _PRICE,
    'renewables': _PCT,
    'state_of_charge': _PCT,
    'power_limit': _PCT,
    'grid_power': _WATTS,
    'solar_power': _WATTS,
    'battery_power': _WATTS,
    'house_power': _WATTS,
}

# Support function to load HTML files from the resources directory.
_JINJA_ENV = Environment(
    loader=FunctionLoader(
        lambda name: (
            (HTML_FILES / name).read_text(encoding='utf-8'),
            None,
            lambda: True
        )
    ),
    autoescape=select_autoescape(['html'])
)


def run_server(host: str, port: int, settings: Settings = _DEFAULT_SETTINGS) -> None:
    """
    Run the server in the current thread.
    Spawns a thread for the control loop.
    """
    control_loop_thread = threading.Thread(target=control_loop.control_loop, daemon=True)
    control_loop_thread.start()

    configure_from_settings(settings)
    uvicorn.run(app, host=host, port=port, workers=1, log_level='info')

    # Cleanly stop the control loop thread
    control_loop.exit_control_loop()
    control_loop_thread.join()


def configure_from_settings(settings: Settings):
    # Initialise power controller connection
    addresses: List[str] = split_addresses(settings.power_controller_addresses)
    if len(addresses) > 0:
        result = control_loop.connect_modbus(addresses[0], addresses[1:])
        LOGGER.info(f'initial power controller connection: {json.dumps(result)}')

    # Initialise power pricer connection
    api_token = settings.power_pricer_api_token.strip()
    nmi = settings.power_pricer_nmi.strip()
    if api_token != '' and nmi != '':
        result = control_loop.connect_amber(api_token, nmi)
        LOGGER.info(f'initial power pricer connection: {json.dumps(result)}')

    # Initialise policy parameters
    result = control_loop.set_parameters(
        disable_export_price_threshold=settings.disable_export_price_threshold,
        enable_export_price_threshold=settings.enable_export_price_threshold,
        start_charge_price_threshold=settings.start_charge_price_threshold,
        stop_charge_price_threshold=settings.stop_charge_price_threshold,
    )
    LOGGER.info(f'initial parameters: {json.dumps(result)}')

    # Initialise control modes
    result = control_loop.set_control(
        battery_mode=settings.battery_mode,
        inverter_mode=settings.inverter_mode,
        battery_policy=settings.battery_policy,
        inverter_policy=settings.inverter_policy,
    )
    LOGGER.info(f'initial modes: {json.dumps(result)}')


def split_addresses(addresses: str) -> List[str]:
    """
    Helper for connecting to devices.
    Split addresses separated by commas, semicolons, ampersands, or whitespace.
    """
    return _ADDRESS_DELIMITERS_PATTERN.split(addresses)


def _format_json(
        data: JSONDict,
        *,
        units: Optional[Dict[str, str]] = None,
        remove_underscores: bool = True,
        indent: int = 2,
) -> str:
    """
    Render JSON data as a formatted string for a human to read.
    """
    if units is None:
        units = {}

    # Replace floats with formatted strings and add units
    data = _stringify_values(None, data, units)

    text = json.dumps(data, indent=indent)
    text = _LINE_ENDINGS_PATTERN.sub('', text)
    text = _BLANK_LINES_PATTERN.sub('', text)
    text = _DICT_ENTRY_SEPARATOR_PATTERN.sub(r'\1 = ', text)

    text = text.replace('"', '')
    if remove_underscores:
        text = text.replace('_', ' ')

    return text


def _stringify_values(key: Optional[str], value: JSONValue, units: Dict[str, str]) -> JSONValue:
    """
    If `value` is a number, return a string rendering of it, including appending units if
    the key is in the `units` dictionary.
    If `value` is a container, return a copy with the items recursively stringified.

    Args:
        key: The key for this value - used to look up units.
        value: The value to stringify.
        units: A lookup table of units to append to values.

    Returns:

    """
    if isinstance(value, float):
        value_str: str = f'{value:.2f}'.rstrip('0').rstrip('.')
        if key is not None and key in units:
            value_str += units[key]
        return value_str
    elif isinstance(value, dict):
        return {k: _stringify_values(k, v, units) for k, v in value.items()}
    elif isinstance(value, list):
        return [_stringify_values(None, v, units) for v in value]
    elif key is not None and key in units:
        return f'{value}{units[key]}'
    else:
        return str(value)


# ====================================================================
#  Server API
# ====================================================================

app = FastAPI()


@app.get('/', response_class=HTMLResponse)
@app.get('/index.html', response_class=HTMLResponse)
def serve_index(request: Request):
    status_json: JSONDict = control_loop.get_status()
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

    except (KeyError, TypeError, IOError) as err:
        LOGGER.error(f'Error getting control status: {err}')
        battery_button = ''
        inverter_button = ''

    templates = Jinja2Templates(env=_JINJA_ENV)
    return templates.TemplateResponse(
        request=request,
        name='index.html',
        context={
            'title': _APP_NAME,
            'status_json': _format_json(status_json, units=_STATUS_UNITS),
            'refresh_interval': _REFRESH_INTERVAL,
            'battery_button': battery_button,
            'inverter_button': inverter_button,
        }
    )


@app.get('/registers.html', response_class=HTMLResponse)
def serve_registers(request: Request):
    json_data: JSONDict = control_loop.get_registers()

    templates = Jinja2Templates(env=_JINJA_ENV)
    return templates.TemplateResponse(
        request=request,
        name='json.html',
        context={
            'title': _APP_NAME,
            'name': 'Registers',
            'json_data': _format_json(json_data, remove_underscores=False),
            'refresh_interval': _REFRESH_INTERVAL,
        }
    )


@app.get('/parameters.html', response_class=HTMLResponse)
def serve_parameters(request: Request):
    json_data: JSONDict = control_loop.get_parameters()
    templates = Jinja2Templates(env=_JINJA_ENV)
    return templates.TemplateResponse(
        request=request,
        name='json.html',
        context={
            'title': _APP_NAME,
            'name': 'Parameters',
            'json_data': _format_json(json_data),
            'refresh_interval': 0,  # no auto refresh
        }
    )


@app.get('/connection.html', response_class=HTMLResponse)
def serve_connection(request: Request):
    json_data: JSONDict = control_loop.get_connection_status()
    templates = Jinja2Templates(env=_JINJA_ENV)
    return templates.TemplateResponse(
        request=request,
        name='json.html',
        context={
            'title': _APP_NAME,
            'name': 'Connection',
            'json_data': _format_json(json_data),
            'refresh_interval': 0,  # no auto refresh
        }
    )


@app.get('/constants.html', response_class=HTMLResponse)
def serve_constants(request: Request):
    json_data: JSONDict = control_loop.Constants.as_dict()
    templates = Jinja2Templates(env=_JINJA_ENV)
    return templates.TemplateResponse(
        request=request,
        name='json.html',
        context={
            'title': _APP_NAME,
            'name': 'Constants',
            'json_data': _format_json(json_data),
            'refresh_interval': 0,  # no auto refresh
        }
    )


@app.get('/status')
def get_status():
    return control_loop.get_status()


@app.get('/status/control')
def get_control():
    return control_loop.get_control_status(),


@app.get('/status/price')
def get_price():
    return control_loop.get_price_status(),


@app.get('/status/power')
def get_power():
    return control_loop.get_power_status(),


@app.get('/registers')
def get_registers():
    return control_loop.get_registers(),


@app.get('/parameters')
def get_parameters():
    return control_loop.get_parameters(),


@app.get('/connection')
def get_connection():
    return control_loop.get_connection_status(),


@app.get('/constants')
def get_constants():
    return control_loop.Constants.as_dict(),


@app.put('/battery/enable')
def set_battery_enable():
    return control_loop.set_control(
        battery_mode=BatteryMode.ENABLE,
        battery_policy=BatteryPolicy.MANUAL,
    )


@app.put('/battery/disable')
def set_battery_disable():
    return control_loop.set_control(
        battery_mode=BatteryMode.DISABLE,
        battery_policy=BatteryPolicy.MANUAL,
    )


@app.put('/battery/force_charge')
def set_battery_force_charge():
    return control_loop.set_control(
        battery_mode=BatteryMode.FORCE_CHARGE,
        battery_policy=BatteryPolicy.MANUAL,
    )


@app.put('/battery/force_discharge')
def set_battery_force_discharge():
    return control_loop.set_control(
        battery_mode=BatteryMode.FORCE_DISCHARGE,
        battery_policy=BatteryPolicy.MANUAL,
    )


@app.put('/battery/cheap_charge')
def set_battery_cheap_charge():
    return control_loop.set_control(
        battery_policy=BatteryPolicy.CHEAP_CHARGE,
    )


@app.put('/inverter/enable')
def set_inverter_enable():
    return control_loop.set_control(
        inverter_mode=InverterMode.ENABLE,
        inverter_policy=InverterPolicy.MANUAL,
    )


@app.put('/inverter/disable')
def set_inverter_disable():
    return control_loop.set_control(
        inverter_mode=InverterMode.DISABLE,
        inverter_policy=InverterPolicy.MANUAL,
    )


@app.put('/inverter/zero_export')
def set_inverter_zero_export():
    return control_loop.set_control(
        inverter_mode=InverterMode.ZERO_EXPORT,
        inverter_policy=InverterPolicy.MANUAL,
    )


@app.put('/inverter/neg_feed_in_zero_export')
def set_inverter_neg_feed_in_zero_export():
    return control_loop.set_control(
        inverter_policy=InverterPolicy.NEG_FEED_IN_ZERO_EXPORT,
    )


@app.put('/parameters')
def set_parameters(
        disable_export_price_threshold: float | None = None,
        enable_export_price_threshold: float | None = None,
        start_charge_price_threshold: float | None = None,
        stop_charge_price_threshold: float | None = None,
):
    result = control_loop.set_parameters(
        disable_export_price_threshold=disable_export_price_threshold,
        enable_export_price_threshold=enable_export_price_threshold,
        start_charge_price_threshold=start_charge_price_threshold,
        stop_charge_price_threshold=stop_charge_price_threshold,
    )

    if 'error' in result.keys():
        status_code = status.HTTP_406_NOT_ACCEPTABLE
    else:
        status_code = status.HTTP_200_OK
    return result, status_code


@app.put('/connection/controller/connect_modbus')
def connect_modbus(addresses: str):
    """
    Establish a modbus connection to the inverter.
    Each address can be a MAC address or an IP address.
    Slave addresses are appended, separated by commas, semicolons, ampersands, or whitespace.
    """
    addresses: List[str] = split_addresses(addresses)
    result = control_loop.connect_modbus(addresses[0], addresses[1:])

    if 'error' in result:
        status_code = status.HTTP_406_NOT_ACCEPTABLE
    else:
        status_code = status.HTTP_200_OK
    return result, status_code


@app.put('/connection/controller/disconnect')
def disconnect_control():
    """
    Close the controller connection to the inverter.
    """
    result = control_loop.disconnect_control()

    if 'error' in result:
        status_code = status.HTTP_406_NOT_ACCEPTABLE
    else:
        status_code = status.HTTP_200_OK
    return result, status_code


@app.put('/connection/pricer/connect_amber')
def connect_amber(
        api_token: str,
        nmi: str,
):
    """
    Establish a connection to Amber as the power pricer.
    The arguments should be an API token (starts with psk_)
    and the meter NMI (string of digits).
    """
    result = control_loop.connect_amber(api_token, nmi)

    if 'error' in result:
        status_code = status.HTTP_406_NOT_ACCEPTABLE
    else:
        status_code = status.HTTP_200_OK
    return result, status_code


@app.put('/connection/pricer/disconnect')
def disconnect_price():
    """
    Close the power pricer connection.
    """
    result = control_loop.disconnect_price()

    if 'error' in result:
        status_code = status.HTTP_406_NOT_ACCEPTABLE
    else:
        status_code = status.HTTP_200_OK
    return result, status_code
