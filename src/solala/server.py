import json
import re
import threading
from typing import List, Optional, Mapping

import uvicorn
from fastapi import FastAPI, Request, status, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from jinja2 import FunctionLoader, select_autoescape, Environment
from pydantic import BaseModel, ConfigDict
from starlette.responses import JSONResponse

from solala import control_loop
from solala.control_loop import BatteryMode, InverterMode, BatteryPolicy, InverterPolicy
from solala.log import LOGGER
from solala.resources import HTML_FILES
from solala.server_nicegui import ui as nicegui_pages
from solala.settings import Settings
from solala.utils.dict_extras import dict_merge
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
    LOGGER.info('waiting for the control loop to terminate')
    control_loop_thread.join()


def configure_from_settings(settings: Settings) -> None:
    """
    Initialise connections, control modes, and policy parameters for `settings`.
    """
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
    Split addresses separated by commas, semicolons, ampersands, or whitespace.
    Helper for connecting to devices.
    """
    return _ADDRESS_DELIMITERS_PATTERN.split(addresses)


def _filter_json(data: JSONDict, match: Optional[str]) -> JSONDict:
    """
    Filter a JSON dictionary by keys containing a given substring.
    """
    if match is None:
        return data
    else:
        return {
            key: value
            for key, value in data.items()
            if match in key
        }


def _format_json(
        data: JSONDict,
        *,
        units: Optional[Mapping[str, str]] = None,
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


def _stringify_values(key: Optional[str], value: JSONValue, units: Mapping[str, str]) -> JSONValue:
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


def _follow_json(rest_of_path: Optional[str], data: JSONDict) -> JSONValue:
    """
    Follow a path through a JSON dictionary.

    Returns:
         the value (if the path exists).
    Raises:
        HTTPException(HTTP_404_NOT_FOUND) if the path does not exist.
    """
    if rest_of_path:
        for part in rest_of_path.split('/'):
            if part not in data:
                raise HTTPException(status.HTTP_404_NOT_FOUND)
            data = data[part]
    return data


def _follow_filter_json(rest_of_path: Optional[str], data: JSONDict, match: Optional[str]) -> JSONValue:
    """
    Apply `follow_json` and then `filter_json` to the data.
    """
    data: JSONValue = _follow_json(rest_of_path, data)
    if isinstance(data, dict) and match is not None:
        return _filter_json(data, match)
    else:
        return data


def _serve_json(
        name: str,
        data: JSONDict,
        request: Request,
        match: str | None = None,
        *,
        units: Optional[Mapping[str, str]] = None,
        remove_underscores: bool = True,
        refresh_interval: int = 0,
):
    """
    Helper for HTTP GET requests that merely serve HTML representation of JSON data.

    Args:
        name: name of the data.
        data: JSON data to be served.
        request: needed for Jinja2Templates.
        match: optional filter to apply to the JSON dict keys.

    Returns:
         filled template HTTP response.
    """
    json_data: JSONDict = _filter_json(data, match)

    templates = Jinja2Templates(env=_JINJA_ENV)
    return templates.TemplateResponse(
        request=request,
        name='json.html',
        context={
            'title': _APP_NAME,
            'name': name,
            'json_data': _format_json(
                json_data,
                units=units,
                remove_underscores=remove_underscores,
            ),
            'refresh_interval': refresh_interval,
        }
    )


# ====================================================================
#  Server API
# ====================================================================

app = FastAPI()


@app.get('/', response_class=HTMLResponse)
@app.get('/index.html', response_class=HTMLResponse)
def index_page(request: Request):
    """
    Serve the landing web page.
    """
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
def registers_page(request: Request, match: str | None = None):
    """
    Show the registers as a formatted web page.
    Optional query argument `match`: filter to apply to the JSON dict keys.
    E.g. "/registers.html?match=master/"
    """
    return _serve_json(
        'Registers',
        control_loop.get_registers(),
        request,
        match,
        remove_underscores=False,
        refresh_interval = _REFRESH_INTERVAL,
    )


@app.get('/parameters.html', response_class=HTMLResponse)
def parameters_page(request: Request, match: str | None = None):
    """
    Show the policy parameters as a formatted web page.
    Optional query argument `match`: filter to apply to the JSON dict keys.
    E.g. "/parameters.html?match=export"
    """
    return _serve_json(
        'Parameters',
        control_loop.get_parameters(),
        request,
        match,
        units=_PARAMETERS_UNITS,
    )


@app.get('/connection.html', response_class=HTMLResponse)
def connection_page(request: Request, match: str | None = None):
    """
    Show the connections as a formatted web page.
    Optional query argument `match`: filter to apply to the JSON dict keys.
    E.g. "/connection.html?match=pricer"
    """
    return _serve_json(
        'Connection',
        control_loop.get_connection_status(),
        request,
        match,
    )


@app.get('/constants.html', response_class=HTMLResponse)
def constants_page(request: Request, match: str | None = None):
    """
    Show the constants as a formatted web page.
    Optional query argument `match`: filter to apply to the JSON dict keys.
    E.g. "/constants.html?match=BUY"
    """
    return _serve_json(
        'Constants',
        control_loop.Constants.as_dict(),
        request,
        match,
        units=_CONSTANTS_UNITS,
    )


@app.get('/status')
def get_status(match: str | None = None):
    return _filter_json(control_loop.get_status(), match)


@app.get('/status/control/{rest_of_path:path}')
def get_control(rest_of_path: str | None = None, match: str | None = None):
    return _follow_filter_json(rest_of_path, control_loop.get_control_status(), match)


@app.get('/status/price/{rest_of_path:path}')
def get_price(rest_of_path: str | None = None, match: str | None = None):
    return _follow_filter_json(rest_of_path, control_loop.get_price_status(), match)


@app.get('/status/power/{rest_of_path:path}')
def get_power(rest_of_path: str | None = None, match: str | None = None):
    return _follow_filter_json(rest_of_path, control_loop.get_power_status(), match)


@app.get('/registers/{rest_of_path:path}')
def get_registers(rest_of_path: str | None = None, match: str | None = None):
    return _follow_filter_json(rest_of_path, control_loop.get_registers(), match)


@app.get('/parameters/{rest_of_path:path}')
def get_parameters(rest_of_path: str | None = None, match: str | None = None):
    return _follow_filter_json(rest_of_path, control_loop.get_parameters(), match)


@app.get('/connection/{rest_of_path:path}')
def get_connection(rest_of_path: str | None = None, match: str | None = None):
    return _follow_filter_json(rest_of_path, control_loop.get_connection_status(), match)


@app.get('/constants/{rest_of_path:path}')
def get_constants(rest_of_path: str | None = None, match: str | None = None):
    return _follow_filter_json(rest_of_path, control_loop.Constants.as_dict(), match)


@app.put('/battery')
def put_battery(mode: str):
    match mode:
        case 'enable':
            return control_loop.set_control(
                battery_mode=BatteryMode.ENABLE,
                battery_policy=BatteryPolicy.MANUAL,
            )
        case 'disable':
            return control_loop.set_control(
                battery_mode=BatteryMode.DISABLE,
                battery_policy=BatteryPolicy.MANUAL,
            )
        case 'force_charge':
            return control_loop.set_control(
                battery_mode=BatteryMode.FORCE_CHARGE,
                battery_policy=BatteryPolicy.MANUAL,
            )
        case 'force_discharge':
            return control_loop.set_control(
                battery_mode=BatteryMode.FORCE_DISCHARGE,
                battery_policy=BatteryPolicy.MANUAL,
            )
        case 'cheap_charge':
            return control_loop.set_control(
                battery_policy=BatteryPolicy.CHEAP_CHARGE,
            )
    return JSONResponse({'error': f'Invalid mode: {mode!r}'}, status.HTTP_422_UNPROCESSABLE_CONTENT)


@app.put('/inverter')
def put_inverter(mode: str):
    match mode:
        case 'enable':
            return control_loop.set_control(
                inverter_mode=InverterMode.ENABLE,
                inverter_policy=InverterPolicy.MANUAL,
            )
        case 'disable':
            return control_loop.set_control(
                inverter_mode=InverterMode.DISABLE,
                inverter_policy=InverterPolicy.MANUAL,
            )
        case 'zero_export':
            return control_loop.set_control(
                inverter_mode=InverterMode.ZERO_EXPORT,
                inverter_policy=InverterPolicy.MANUAL,
            )
        case 'neg_feed_in_zero_export':
            return control_loop.set_control(
                inverter_policy=InverterPolicy.NEG_FEED_IN_ZERO_EXPORT,
            )
    return JSONResponse({'error': f'Invalid mode: {mode!r}'}, status.HTTP_422_UNPROCESSABLE_CONTENT)


@app.put('/parameters/{parameter}')
def put_parameters(parameter: str, value: float):
    if parameter not in control_loop.get_parameters():
        return JSONResponse({'error': f'Invalid parameter: {parameter!r}'}, status.HTTP_422_UNPROCESSABLE_CONTENT)

    kwargs = {parameter: value}
    result = control_loop.set_parameters(**kwargs)
    if 'error' in result.keys():
        status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    else:
        status_code = status.HTTP_200_OK
    return JSONResponse(result, status_code=status_code)


class ControllerConnectionUpdate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    type: str = 'modbus'
    addresses: str


@app.put('/connection/controller/connect')
def put_controller_connect(payload: ControllerConnectionUpdate):
    """
    Establish a modbus connection to the inverter.
    Each address can be a MAC address or an IP address.
    Slave addresses are appended, separated by commas, semicolons, ampersands, or whitespace.
    """
    if payload.type != 'modbus':
        return JSONResponse({'error': 'only modbus is supported'}, status_code=status.HTTP_400_BAD_REQUEST)

    addresses: List[str] = split_addresses(payload.addresses)
    result = control_loop.connect_modbus(addresses[0], addresses[1:])

    if 'error' in result:
        status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    else:
        status_code = status.HTTP_200_OK
    return JSONResponse(result, status_code=status_code)


@app.put('/connection/controller/disconnect')
def put_controller_disconnect():
    """
    Close the controller connection to the inverter.
    """
    return control_loop.disconnect_control()


class PricerConnectionUpdate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    type: str = 'amber'
    api_token: str
    nmi: str


@app.put('/connection/pricer/connect')
def put_pricer_connect(payload: PricerConnectionUpdate):
    """
    Establish a connection to Amber as the power pricer.
    The arguments should be an API token (starts with psk_)
    and the meter NMI (string of digits).
    """
    if payload.type != 'amber':
        return JSONResponse({'error': 'only amber is supported'}, status_code=status.HTTP_400_BAD_REQUEST)

    result = control_loop.connect_amber(payload.api_token, payload.nmi)

    if 'error' in result:
        status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    else:
        status_code = status.HTTP_200_OK
    return JSONResponse(result, status_code=status_code)


@app.put('/connection/pricer/disconnect')
def put_pricer_disconnect():
    """
    Close the power pricer connection.
    """
    return control_loop.disconnect_price()


# Mount NiceGUI onto the FastAPI app (processes all nicegui pages).
# This must come last.
nicegui_pages.run_with(app, title="My App Dashboard")
