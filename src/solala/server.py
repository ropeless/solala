import json
import re
import threading
from typing import List

import uvicorn
from fastapi import FastAPI, Request, status
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from jinja2 import FunctionLoader, select_autoescape, Environment

from solala import control_loop
from solala.control_loop import BatteryMode, ExportMode, BatteryPolicy, ExportPolicy, _LOOP_SLEEP
from solala.log import LOGGER
from solala.resources import HTML_FILES
from solala.settings import Settings
from solala.utils.json import JSONDict, json_dict, JSONValue

_ADDRESS_DELIMITERS_PATTERN = re.compile(r'[,;\s]+')
_LINE_ENDINGS_PATTERN = re.compile(r'}?[,{}]\s*(?=\n|$)')
_BLANK_LINES_PATTERN = re.compile(r'^[ \t]*\r?\n', flags=re.MULTILINE)

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

_DEFAULT_SETTINGS = Settings()


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
        export_mode=settings.export_mode,
        battery_policy=settings.battery_policy,
        export_policy=settings.export_policy,
    )
    LOGGER.info(f'initial modes: {json.dumps(result)}')


def split_addresses(addresses: str) -> List[str]:
    """
    Helper for connecting to devices.
    Split addresses separated by commas, semicolons, or whitespace.
    """
    return _ADDRESS_DELIMITERS_PATTERN.split(addresses)


def _format_json(data: JSONDict) -> str:
    """
    Render JSON data as a formatted string for a human to read.
    """

    # Replace floats with formatted strings
    data = _stringify_floats(data)

    text = json.dumps(data, indent=4)
    text = _LINE_ENDINGS_PATTERN.sub('', text)
    text = _BLANK_LINES_PATTERN.sub('', text)
    text = text.replace('_', ' ').replace('"', '')
    return text


def _stringify_floats(data: JSONValue) -> JSONValue:
    if isinstance(data, float):
        return f'{data:.2f}'
    elif isinstance(data, dict):
        return {k: _stringify_floats(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [_stringify_floats(v) for v in data]
    else:
        return data


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
        export_status: JSONDict = json_dict(control_json['export'])

        battery_mode = battery_status['mode']
        battery_policy = battery_status['policy']
        battery_button = (
            battery_policy
            if battery_policy != BatteryPolicy.MANUAL.name
            else battery_mode
        )
        export_mode = export_status['mode']
        export_policy = export_status['policy']
        export_button = (
            export_policy
            if export_policy != ExportPolicy.MANUAL.name
            else export_mode
        )

    except (KeyError, TypeError, IOError) as err:
        LOGGER.error(f'Error getting control status: {err}')
        battery_button = ''
        export_button = ''

    templates = Jinja2Templates(env=_JINJA_ENV)
    return templates.TemplateResponse(
        request=request,
        name='index.html',
        context={
            'title': 'Solala',
            'status_json': _format_json(status_json),
            'refresh_interval': _LOOP_SLEEP,
            'battery_button': battery_button,
            'export_button': export_button,
        }
    )


@app.get('/registers.html', response_class=HTMLResponse)
def serve_index(request: Request):
    registers_json: JSONDict = control_loop.get_registers()

    templates = Jinja2Templates(env=_JINJA_ENV)
    return templates.TemplateResponse(
        request=request,
        name='registers.html',
        context={
            'title': 'Solala',
            'registers_json': _format_json(registers_json),
            'refresh_interval': _LOOP_SLEEP,
        }
    )


@app.get('/status')
def get_status():
    return control_loop.get_status()


@app.get('/status/control')
def get_control():
    return {
        'control': control_loop.get_control_status(),
    }


@app.get('/status/price')
def get_price():
    return {
        'price': control_loop.get_price_status(),
    }


@app.get('/status/power')
def get_power():
    return {
        'power': control_loop.get_power_status(),
    }


@app.get('/registers')
def get_registers():
    return {
        'registers': control_loop.get_registers(),
    }


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


@app.put('/export/enable')
def set_export_enable():
    return control_loop.set_control(
        export_mode=ExportMode.ENABLE,
        export_policy=ExportPolicy.MANUAL,
    )


@app.put('/export/disable')
def set_export_disable():
    return control_loop.set_control(
        export_mode=ExportMode.DISABLE,
        export_policy=ExportPolicy.MANUAL,
    )


@app.put('/export/neg_feed_in_disable')
def set_export_neg_feed_in_disable():
    return control_loop.set_control(
        export_policy=ExportPolicy.NEG_FEED_IN_DISABLE,
    )


@app.put('/parameters')
@app.get('/parameters')  # DEBUG
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



@app.put('/control/connect_modbus/{addresses}')
def connect_modbus(addresses: str):
    """
    Establish a modbus connection to the inverter.
    Address can be a MAC address or an IP address.
    Slave addresses are appended, separated by commas, semicolons, or whitespace.
    """
    addresses: List[str] = split_addresses(addresses)
    result = control_loop.connect_modbus(addresses[0], addresses[1:])

    if result['connect_modbus'] == 'Success':
        status_code = status.HTTP_200_OK
    else:
        status_code = status.HTTP_406_NOT_ACCEPTABLE
    return result, status_code


@app.put('/control/disconnect')
def disconnect_control():
    """
    Close the controller connection to the inverter.
    """
    return control_loop.disconnect_control()


@app.put('/price/connect_amber')
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

    if result['connect_modbus'] == 'Success':
        status_code = status.HTTP_200_OK
    else:
        status_code = status.HTTP_406_NOT_ACCEPTABLE
    return result, status_code


@app.put('/price/disconnect')
def disconnect_price():
    """
    Close the power pricer connection.
    """
    return control_loop.disconnect_price()
