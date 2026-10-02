import threading
from functools import partial
from http import HTTPStatus
from pathlib import Path
from typing import List, Optional

import uvicorn
from fastapi import FastAPI, Request, status, HTTPException
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from solala import control_loop
from solala.control_loop import BatteryMode, InverterMode, BatteryPolicy, InverterPolicy, ControlLoopError
from solala.server_constants import APP_NAME
from solala.server_constants import LOGGER
from solala.server_nicegui import ui
from solala.control_loop.settings import Settings
from solala.utils.json import JSONDict, JSONValue, filter_json, follow_json
from solala.utils.string_extras import split_addresses


def run_server(
        host: str,
        port: int,
        settings_path: Optional[Path|str] = None,
        settings: Optional[Settings] = None,
        force_settings: bool = False,
) -> None:
    """
    Run the server in the current thread.
    Spawns a thread for the control loop.
    Args:
        host: Host address to bind the server to.
        port: Port to bind the server to.

        settings_path: Path to the settings file, if settings are to be persisted. If provided, the control
            loop will attempt to load settings from the file.

        settings: Settings object to use if the settings file cannot be loaded.

        force_settings: If True, the given settings object will always override any settings loaded from the file.
            Note that if settings are provided, they will override any settings loaded from the file. This includes
            modes and policies if the power controller is reloaded.
    """
    target = partial(control_loop.run_control_loop, settings_path, settings, force_settings)
    control_loop_thread = threading.Thread(target=target, daemon=True)
    control_loop_thread.start()

    uvicorn.run(app, host=host, port=port, workers=1, log_level='info')

    # Cleanly stop the control loop thread
    control_loop.exit_control_loop()
    LOGGER.info('waiting for the control loop to terminate')
    control_loop_thread.join()


def _follow_filter_json(data: JSONDict, path: Optional[str], match: Optional[str]) -> JSONValue:
    """
    Apply `follow_json` then `filter_json` to the data.
    """
    try:
        data: JSONValue = follow_json(data, path)
    except KeyError as err:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f'Invalid path: {err}')
    if isinstance(data, dict) and match is not None:
        data = filter_json(data, match)
    return data


# ====================================================================
#  Server API
# ====================================================================

app = FastAPI()


@app.exception_handler(ControlLoopError)
async def handle_control_loop_error(request: Request, err: ControlLoopError):
    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    status_string = HTTPStatus(status_code).phrase

    # Construct an RFC 9457 dictionary as the response content
    content: JSONDict = {
        'type': 'https://www.rfc-editor.org/rfc/rfc9457',
        'title': status_string,
        'status': status_code,
        'detail': err.detail,
        'instance': str(request.base_url),
    }
    if err.errors is not None:
        content['errors'] = err.errors

    # RFC 9457 requires the 'application/problem+json' Media Type
    return JSONResponse(
        status_code=status_code,
        content=content,
        headers={"Content-Type": "application/problem+json"}
    )


@app.exception_handler(HTTPException)
async def handle_http_error(request: Request, err: HTTPException):
    status_code = err.status_code
    status_string = HTTPStatus(status_code).phrase

    # Construct an RFC 9457 dictionary as the response content
    content: JSONDict = {
        'type': 'https://www.rfc-editor.org/rfc/rfc9457',
        'title': status_string,
        'status': status_code,
        'detail': err.detail,
        'instance': str(request.base_url),
    }

    # RFC 9457 requires the 'application/problem+json' Media Type
    return JSONResponse(
        status_code=status_code,
        content=content,
        headers={"Content-Type": "application/problem+json"}
    )


@app.get('/schema', include_in_schema=False)
def get_schema():
    openapi_schema = get_openapi(
        title=app.title,
        version=app.version,
        routes=app.routes,
    )
    return openapi_schema


@app.get('/status')
def get_status(match: str | None = None):
    return filter_json(control_loop.get_status(), match)


@app.get('/status/control')
@app.get('/status/control/{rest_of_path:path}')
def get_control(rest_of_path: Optional[str] = None, match: str | None = None):
    return _follow_filter_json(control_loop.get_control_status(), rest_of_path, match)


@app.get('/status/price')
@app.get('/status/price/{rest_of_path:path}')
def get_price(rest_of_path: str | None = None, match: str | None = None):
    return _follow_filter_json(control_loop.get_price_status(), rest_of_path, match)


@app.get('/status/power')
@app.get('/status/power/{rest_of_path:path}')
def get_power(rest_of_path: str | None = None, match: str | None = None):
    return _follow_filter_json(control_loop.get_power_status(), rest_of_path, match)


@app.get('/status/charger')
@app.get('/status/charger/{rest_of_path:path}')
def get_charger(rest_of_path: str | None = None, match: str | None = None):
    return _follow_filter_json(control_loop.get_car_charger_status(), rest_of_path, match)


@app.get('/registers')
@app.get('/registers/{rest_of_path:path}')
def get_registers(rest_of_path: str | None = None, match: str | None = None):
    return _follow_filter_json(control_loop.get_registers(), rest_of_path, match)


@app.get('/parameters')
@app.get('/parameters/{rest_of_path:path}')
def get_parameters(rest_of_path: str | None = None, match: str | None = None):
    return _follow_filter_json(control_loop.get_parameters(), rest_of_path, match)


@app.get('/connection')
@app.get('/connection/{rest_of_path:path}')
def get_connection(rest_of_path: str | None = None, match: str | None = None):
    return _follow_filter_json(control_loop.get_connection_status(), rest_of_path, match)


@app.get('/constants')
@app.get('/constants/{rest_of_path:path}')
def get_constants(rest_of_path: str | None = None, match: str | None = None):
    return _follow_filter_json(control_loop.Constants.as_dict(), rest_of_path, match)


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
    return control_loop.set_parameters(**kwargs)


class ControllerConnectionUpdate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    type: str = 'modbus'
    addresses: str


@app.put('/connection/controller/connect')
def put_controller_connect(payload: ControllerConnectionUpdate):
    """
    Establish a modbus connection to the inverter.
    Each address can be a MAC address or an IP address.
    Slave address are appended, separated by commas, semicolons, ampersands, or whitespace.
    """
    if payload.type != 'modbus':
        return JSONResponse({'error': 'only modbus is supported'}, status_code=status.HTTP_400_BAD_REQUEST)

    addresses: List[str] = split_addresses(payload.addresses)
    result = control_loop._connect_modbus(addresses[0], addresses[1:])

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
    return control_loop.disconnect_controller()


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

    result = control_loop._connect_amber(payload.api_token, payload.nmi)

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
    return control_loop.disconnect_pricer()


# Mount NiceGUI onto the FastAPI app (processes all nicegui pages).
# This must come last.
ui.run_with(app, title=APP_NAME, favicon='http://localhost/images/solala-32x32.png')
