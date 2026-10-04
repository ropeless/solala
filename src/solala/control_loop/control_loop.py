import json
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, UTC, timedelta
from pathlib import Path
from typing import Optional, List, Iterable, Dict, Tuple

from pymodbus.client import ModbusTcpClient

from solala.car_charger.impl_tesla_wall_connector.tesla_wall_connector import TeslaWallConnector
from solala.car_charger.wall_charger import CarCharger, ChargerStatus
from solala.control_loop.constants import Constants
from solala.control_loop.errors import ControlLoopError
from solala.control_loop.listeners import RegistersListener, StatusListener
from solala.control_loop.modes_and_policies import BatteryMode, InverterMode, BatteryPolicy, InverterPolicy
from solala.control_loop.settings import Settings, AmberPricerConnection, ModbusControllerConnection, \
    TeslaChargerConnection, ControllerConnection, PricerConnection, ChargerConnection, \
    DEFAULT_DISABLE_FEED_IN_PRICE_THRESHOLD, DEFAULT_ENABLE_FEED_IN_PRICE_THRESHOLD, \
    DEFAULT_START_CHARGE_PRICE_THRESHOLD, DEFAULT_STOP_CHARGE_PRICE_THRESHOLD
from solala.power_controller.impl_modbus.modbus import Modbus, ModbusDevice
from solala.power_controller.impl_modbus.modbus_power_controller import PowerController, ModbusPowerController
from solala.power_pricer.impl_amber.amber_power_pricer import Price, AmberPowerPricer
from solala.power_pricer.power_pricer import PowerPricer
from solala.server_constants import LOGGER, DATE_FORMAT
from solala.utils.json import JSONDict
from solala.utils.network import find_ip_by_mac
from solala.utils.string_extras import split_addresses

_LOG_SRC = '[control loop] '  # prefix for log messages

_MIN_DATE = datetime.min.replace(tzinfo=UTC)
_NO_PRICE = Price(
    start_time=_MIN_DATE,
    end_time=_MIN_DATE,
    renewables=0,
    buy_price=0,
    feed_in_price=0,
    estimate=True,
)
_NO_CHARGER = ChargerStatus(0, 0)


def _disconnected() -> JSONDict:
    """
    Returns:
        The standard status message for when a connection is disconnected.
    """
    return {'status': 'disconnected'}


@dataclass
class _ControlState:
    controller: Optional[PowerController] = None
    pricer: Optional[PowerPricer] = None
    charger: Optional[CarCharger] = None

    settings_controller: Optional[ControllerConnection] = None
    settings_pricer: Optional[PricerConnection] = None
    settings_charger: Optional[ChargerConnection] = None

    power_controller_status: JSONDict = field(default_factory=_disconnected)
    power_pricer_status: JSONDict = field(default_factory=_disconnected)
    car_charger_status: JSONDict = field(default_factory=_disconnected)

    battery_mode: BatteryMode = BatteryMode.UNKNOWN
    inverter_mode: InverterMode = InverterMode.UNKNOWN
    battery_policy: BatteryPolicy = BatteryPolicy.MANUAL
    inverter_policy: InverterPolicy = InverterPolicy.MANUAL

    last_price: Price = _NO_PRICE
    next_price_settle_check: datetime = _MIN_DATE
    next_feed_in_price_check: datetime = _MIN_DATE
    next_buy_price_check: datetime = _MIN_DATE

    # NEG_FEED_IN_ZERO_EXPORT parameters
    disable_export_price_threshold: float = DEFAULT_DISABLE_FEED_IN_PRICE_THRESHOLD
    enable_export_price_threshold: float = DEFAULT_ENABLE_FEED_IN_PRICE_THRESHOLD

    # CHEAP_CHARGE parameters
    start_charge_price_threshold: float = DEFAULT_START_CHARGE_PRICE_THRESHOLD
    stop_charge_price_threshold: float = DEFAULT_STOP_CHARGE_PRICE_THRESHOLD

    control_loop_status_listeners: List[StatusListener] = field(default_factory=list)
    control_loop_registers_listeners: List[RegistersListener] = field(default_factory=list)

    settings_path: Optional[Path] = None  # for using persisted settings.
    loop_start: datetime = datetime.now(UTC)  # confirms the control loop is running

    def reset_controller(self, controller: Optional[PowerController]) -> None:
        self.controller = controller
        self.battery_mode = BatteryMode.UNKNOWN
        self.inverter_mode = InverterMode.UNKNOWN
        self.inverter_policy = InverterPolicy.MANUAL

        self.last_price: Price = _NO_PRICE
        self.next_price_settle_check = _MIN_DATE
        self.next_feed_in_price_check = _MIN_DATE
        self.next_buy_price_check = _MIN_DATE

        if controller is None:
            self.power_controller_status = _disconnected()

    def reset_pricer(self, pricer: Optional[PowerPricer]) -> None:
        self.pricer = pricer
        self.last_price: Price = _NO_PRICE
        self.next_price_settle_check = _MIN_DATE
        self.next_feed_in_price_check: datetime = _MIN_DATE
        self.next_buy_price_check: datetime = _MIN_DATE

        if pricer is None:
            self.power_pricer_status = _disconnected()

    def reset_car_charger(self, car_charger: Optional[CarCharger]) -> None:
        self.charger = car_charger

        if car_charger is None:
            self.car_charger_status = _disconnected()

    def copy_listeners(self) -> Tuple[List[StatusListener], List[RegistersListener]]:
        status_listeners = self.control_loop_status_listeners.copy()
        registers_listeners = self.control_loop_registers_listeners.copy()
        return status_listeners, registers_listeners


@dataclass
class _PrevControlState:
    controller: Optional[PowerController] = None
    battery_mode: BatteryMode = BatteryMode.UNKNOWN
    inverter_mode: InverterMode = InverterMode.UNKNOWN
    battery_policy: BatteryPolicy = BatteryPolicy.MANUAL
    inverter_policy: InverterPolicy = InverterPolicy.MANUAL

    def reset(self, controller: Optional[PowerController]) -> None:
        self.controller = controller
        self.battery_mode = BatteryMode.UNKNOWN
        self.inverter_mode = InverterMode.UNKNOWN
        self.battery_policy = BatteryPolicy.MANUAL
        self.inverter_policy = InverterPolicy.MANUAL


# Global server state variables
_control_state_lock = threading.RLock()
_control_state: _ControlState = _ControlState()
_control_loop_running: bool = True


def run_control_loop(
        settings_path: Optional[Path | str] = None,
        settings: Optional[Settings] = None,
        force_settings: bool = False,
) -> None:
    """
    The control loop is an infinite loop to implement the
    control logic of the battery and inverter modes and policies.

    Multiple thread-safe functions are provided to manage the
    behaviour of the control loop.

    Call `exit_control_loop()` to gracefully terminate the control loop.

    Args:
        settings_path: Path to the settings file, if settings are to be persisted. If provided, the control
            loop will attempt to load settings from the file.

        settings: Settings object to use if the settings file cannot be loaded.

        force_settings: If True, the given settings object will always override any settings loaded from the file.
            Note that if settings are provided, they will override any settings loaded from the file. This includes
            modes and policies if the power controller is reloaded.
    """
    LOGGER.info(f'{_LOG_SRC}Running')

    # Prepare to run the control loop.
    global _control_loop_running
    _control_loop_running = True
    prev_state: _PrevControlState = _PrevControlState()

    # Configure and user settings
    _control_state.settings_path = Path(settings_path) if settings_path is not None else None
    loaded: bool = _load_settings()
    if (not loaded or force_settings) and settings is not None:
        configure_from_settings(settings)

    while _control_loop_running:

        with _control_state_lock:
            state = _control_state
            state.loop_start = datetime.now(UTC)  # to calculate loop sleep time
            status_listeners, registers_listeners = _control_step(state, prev_state)

        _update_listeners(status_listeners, registers_listeners)

        # Sleep for the remaining time until the next loop iteration
        sleeptime: int = int(state.loop_start.timestamp() + Constants.LOOP_TIME - datetime.now().timestamp())
        if sleeptime < Constants.MIN_SLEEP_TIME:
            LOGGER.warn(f'{_LOG_SRC}Low sleep time: {sleeptime} < {Constants.MIN_SLEEP_TIME}')
            sleeptime = Constants.MIN_SLEEP_TIME
        time.sleep(sleeptime)


def _control_step(
        state: _ControlState,
        prev_state: _PrevControlState,
) -> Tuple[
    List[StatusListener],
    List[RegistersListener],
]:
    """
    Perform one functional step of the control loop.
    This function will grab the control state lock.
    No work is performed if the power controller is None.
    No non-manual policies are performed if the power pricer is None.

    Args:
        state: the current control state
        prev_state: the previous control state

    Returns:
        a copy of the listeners, copied before the control state lock is released
    """
    if state.controller is None:
        prev_state.reset(None)
        return state.copy_listeners()
    power_controller: PowerController = state.controller
    if power_controller is not prev_state.controller:
        prev_state.reset(power_controller)

    # Battery Policy - may change Battery Mode
    if state.pricer is not None:
        if state.battery_policy == BatteryPolicy.CHEAP_CHARGE:
            if state.next_buy_price_check <= datetime.now(UTC):
                # time to check the price again
                prices = _update_price()
                price = state.last_price
                buy_price = price.buy_price
                if buy_price < state.start_charge_price_threshold:
                    state.battery_mode = BatteryMode.FORCE_CHARGE
                elif buy_price > state.enable_export_price_threshold:
                    state.battery_mode = BatteryMode.ENABLE
                _update_price_check(prices)

    # Battery Mode
    if state.battery_mode != prev_state.battery_mode:
        match state.battery_mode:
            case BatteryMode.ENABLE:
                power_controller.enable_battery()
            case BatteryMode.DISABLE:
                power_controller.disable_battery()
            case BatteryMode.FORCE_CHARGE:
                power_controller.force_charge()
            case BatteryMode.FORCE_DISCHARGE:
                power_controller.force_discharge()
        prev_state.battery_mode = state.battery_mode

    # Inverter Policy - may change Inverter Mode
    if state.pricer is not None:
        if state.inverter_policy == InverterPolicy.NEG_FEED_IN_ZERO_EXPORT:
            if state.next_feed_in_price_check <= datetime.now(UTC):
                # time to check the price again
                prices = _update_price()
                price = state.last_price
                feed_in_price = price.feed_in_price
                if feed_in_price < state.disable_export_price_threshold:
                    state.inverter_mode = InverterMode.ZERO_EXPORT
                elif feed_in_price > state.disable_export_price_threshold:
                    state.inverter_mode = InverterMode.ENABLE
                _update_price_check(prices)

    # Inverter Mode
    if state.inverter_mode != prev_state.inverter_mode:
        if state.inverter_mode == InverterMode.ENABLE:
            power_controller.enable_inverter()
        # All other cases managed below as they have a reversion time limit
        prev_state.inverter_mode = state.inverter_mode
    # Inverter modes requiring keep-alive pulse
    try:
        match state.inverter_mode:
            case InverterMode.DISABLE:
                power_controller.disable_inverter(change_duration=Constants.CONTROL_DURATION)
            case InverterMode.ZERO_EXPORT:
                power_controller.zero_export(change_duration=Constants.CONTROL_DURATION)
    except Exception as e:
        LOGGER.error(f'{_LOG_SRC}Error processing command: {state.inverter_mode}. Error: {e}')

    return state.copy_listeners()


# =============================================================================
#  Control loop interaction
# =============================================================================


def loop_stale() -> bool:
    """
    The control loop is expected to iterate each `Constants.LOOP_TIME` seconds.
    If it has been more than twice that time, then the loop is likely stale.

    Returns:
        True if the control loop appears to be stale, False otherwise.
    """
    # We are not concerned with race conditions, so we do not need to get the control loop lock.
    seconds_since_last_loop: float = datetime.now(UTC).timestamp() - _control_state.loop_start.timestamp()
    return seconds_since_last_loop > 2 * Constants.LOOP_TIME


def configure_from_settings(settings: Settings) -> None:
    """
    Initialise connections, control modes, policies, etc. as per `settings`.
    """

    # Configure power controller connection
    if settings.controller is not None:
        connect_controller(settings.controller)

    # Configure power pricer connection
    if settings.pricer is not None:
        connect_pricer(settings.pricer)

    # Configure car charger connection
    if settings.charger is not None:
        connect_car_charger(settings.charger)

    # Configure policy parameters
    result = set_parameters(
        disable_export_price_threshold=settings.disable_export_price_threshold,
        enable_export_price_threshold=settings.enable_export_price_threshold,
        start_charge_price_threshold=settings.start_charge_price_threshold,
        stop_charge_price_threshold=settings.stop_charge_price_threshold,
    )
    LOGGER.info(f'{_LOG_SRC}Policy parameters: {json.dumps(result)}')

    # Initialise control modes
    result = set_control(
        battery_mode=settings.battery_mode,
        inverter_mode=settings.inverter_mode,
        battery_policy=settings.battery_policy,
        inverter_policy=settings.inverter_policy,
    )
    LOGGER.info(f'{_LOG_SRC}Modes: {json.dumps(result)}')


def get_settings() -> Settings:
    with _control_state_lock:
        return Settings(
            controller=_control_state.settings_controller,
            pricer=_control_state.settings_pricer,
            charger=_control_state.settings_charger,

            battery_mode=_control_state.battery_mode,
            inverter_mode=_control_state.inverter_mode,
            battery_policy=_control_state.battery_policy,
            inverter_policy=_control_state.inverter_policy,

            disable_export_price_threshold=_control_state.disable_export_price_threshold,
            enable_export_price_threshold=_control_state.enable_export_price_threshold,

            start_charge_price_threshold=_control_state.start_charge_price_threshold,
            stop_charge_price_threshold=_control_state.stop_charge_price_threshold,
        )


def add_listener(listener: StatusListener | RegistersListener):
    with _control_state_lock:
        state = _control_state
        remove_listener(listener)
        if isinstance(listener, StatusListener):
            state.control_loop_status_listeners.append(listener)
        elif isinstance(listener, RegistersListener):
            state.control_loop_registers_listeners.append(listener)
        else:
            raise ValueError(f'Invalid listener type: {listener!r}')


def remove_listener(listener: StatusListener | RegistersListener):
    with _control_state_lock:
        state = _control_state
        try:
            if isinstance(listener, StatusListener):
                state.control_loop_status_listeners.remove(listener)
            elif isinstance(listener, RegistersListener):
                state.control_loop_registers_listeners.remove(listener)
            else:
                raise ValueError(f'Invalid listener type: {listener!r}')
        except ValueError:
            pass


def update_listeners() -> None:
    """
    Call `update` on all registered control loop listeners.
    """
    with _control_state_lock:
        state = _control_state
        status_listeners, registers_listeners = state.copy_listeners()
    _update_listeners(status_listeners, registers_listeners)


def get_control_status() -> JSONDict:
    with _control_state_lock:
        battery: JSONDict = {
            'mode': _control_state.battery_mode.name,
            'policy': _control_state.battery_policy.name,
        }
        inverter: JSONDict = {
            'mode': _control_state.inverter_mode.name,
            'policy': _control_state.inverter_policy.name,
        }
        if _control_state.battery_policy == BatteryPolicy.CHEAP_CHARGE:
            battery.update({
                'next_buy_price_check': _control_state.next_buy_price_check.strftime(DATE_FORMAT),
                'start_charge_price_threshold': _control_state.start_charge_price_threshold,
                'stop_charge_price_threshold': _control_state.stop_charge_price_threshold,
            })
        if _control_state.inverter_policy == InverterPolicy.NEG_FEED_IN_ZERO_EXPORT:
            inverter.update({
                'next_feed_in_price_check': _control_state.next_feed_in_price_check.strftime(DATE_FORMAT),
                'disable_export_price_threshold': _control_state.disable_export_price_threshold,
                'enable_export_price_threshold': _control_state.enable_export_price_threshold,
            })

        return {
            'battery': battery,
            'inverter': inverter,
        }


def get_price_status() -> JSONDict:
    with _control_state_lock:
        if _control_state.pricer is None:
            return _control_state.power_pricer_status
        try:
            cur_price: Price = get_cur_price()
            result = cur_price.as_dict(DATE_FORMAT, include_time=False)
            return result
        except Exception as e:
            raise ControlLoopError('failed to get price', errors={'error': str(e)})


def get_power_status() -> JSONDict:
    with _control_state_lock:
        if _control_state.controller is None:
            return _control_state.power_controller_status
        try:
            result = _control_state.controller.get_status().as_dict()
            return result
        except Exception as e:
            raise ControlLoopError('failed to get power status', errors={'error': str(e)})


def get_car_charger_status() -> JSONDict:
    with _control_state_lock:
        if _control_state.charger is None:
            return _control_state.car_charger_status
        try:
            result = _control_state.charger.get_status().as_dict()
            return result
        except Exception as e:
            raise ControlLoopError('failed to get car charger status', errors={'error': str(e)})


def get_connection_status() -> JSONDict:
    with _control_state_lock:
        return {
            'controller': _control_state.power_controller_status,
            'pricer': _control_state.power_pricer_status,
            'charger': _control_state.car_charger_status,
        }


def get_status() -> JSONDict:
    with _control_state_lock:
        return {
            'control': get_control_status(),
            'price': get_price_status(),
            'power': get_power_status(),
            'charger': get_car_charger_status(),
        }


def get_parameters() -> JSONDict:
    with _control_state_lock:
        state = _control_state
        return {
            'start_charge_price_threshold': state.start_charge_price_threshold,
            'stop_charge_price_threshold': state.stop_charge_price_threshold,
            'disable_export_price_threshold': state.disable_export_price_threshold,
            'enable_export_price_threshold': state.enable_export_price_threshold,
        }


def get_registers() -> Dict[str, int | float | str | bool]:
    """
    Raises:
        ControlLoopError: if a power controller is not connected
    """
    with _control_state_lock:
        state = _control_state
        if state.controller is None:
            raise ControlLoopError('power controller not connected')
        else:
            return {
                register: value
                for register, value in state.controller.get_registers()
            }


def get_cur_price() -> Price:
    with _control_state_lock:
        state = _control_state
        price: Price = state.last_price
        pricer = state.pricer
        if pricer is None:
            LOGGER.error(f'{_LOG_SRC}Price update not available. Error: power pricer not connected')
            return price

        now = datetime.now(UTC)
        if state.next_price_settle_check <= now:
            try:
                price: Price = pricer.get_price(0)[0]
                state.last_price = price

                if price.estimate:
                    # price is unstable - recheck is needed
                    delay = Constants.PRICE_SETTLE_CHECK
                    state.next_price_settle_check = min(now + timedelta(seconds=delay), price.end_time)
                else:
                    # price is stable - no need to recheck for this period
                    state.next_price_settle_check = price.end_time

            except Exception as err:
                LOGGER.error(f'{_LOG_SRC}Price update not available. Error: {err}')
    return price


def get_cur_car_charger() -> ChargerStatus:
    with _control_state_lock:
        car_charger = _control_state.charger
        if car_charger is None:
            LOGGER.error(f'{_LOG_SRC}Car charger status not available. Error: car charger not connected')
            return _NO_CHARGER
        else:
            return car_charger.get_status()


def set_control(
        *,
        battery_mode: Optional[BatteryMode] = None,
        inverter_mode: Optional[InverterMode] = None,
        battery_policy: Optional[BatteryPolicy] = None,
        inverter_policy: Optional[InverterPolicy] = None
) -> JSONDict:
    with _control_state_lock:
        state = _control_state

        if battery_mode is not None:
            state.battery_mode = battery_mode
        if inverter_mode is not None:
            state.inverter_mode = inverter_mode
        if battery_policy is not None:
            state.battery_policy = battery_policy
        if inverter_policy is not None:
            state.inverter_policy = inverter_policy

        _save_settings()
        _force_price_check()
        return get_control_status()


def set_parameters(
        *,
        # NEG_FEED_IN_ZERO_EXPORT parameters
        disable_export_price_threshold: Optional[float] = None,
        enable_export_price_threshold: Optional[float] = None,
        # CHEAP_CHARGE parameters
        start_charge_price_threshold: Optional[float] = None,
        stop_charge_price_threshold: Optional[float] = None,
) -> JSONDict:
    """
    Set the price threshold for the battery and inverter policies.

    Raises:
        ControlLoopError: parameters are invalid, collectively or individually.
    """
    with _control_state_lock:
        state = _control_state

        if disable_export_price_threshold is None:
            disable_export_price_threshold = state.disable_export_price_threshold
        if enable_export_price_threshold is None:
            enable_export_price_threshold = state.enable_export_price_threshold
        if start_charge_price_threshold is None:
            start_charge_price_threshold = state.start_charge_price_threshold
        if stop_charge_price_threshold is None:
            stop_charge_price_threshold = state.stop_charge_price_threshold

        if disable_export_price_threshold >= enable_export_price_threshold:
            raise ControlLoopError('export price threshold: disable must be less than enable')
        if start_charge_price_threshold >= stop_charge_price_threshold:
            raise ControlLoopError('charge price threshold: start must be less than stop')

        state.disable_export_price_threshold = disable_export_price_threshold
        state.enable_export_price_threshold = enable_export_price_threshold
        state.start_charge_price_threshold = start_charge_price_threshold
        state.stop_charge_price_threshold = stop_charge_price_threshold

        _save_settings()
        _force_price_check()
        return get_parameters()


def exit_control_loop() -> None:
    """
    Flag to exit the control loop on the next iteration.
    """
    # No need to acquire lock
    global _control_loop_running
    _control_loop_running = False


# =============================================================================
#  Connection management for power control and price
# =============================================================================

def connect_controller(controller: ControllerConnection) -> JSONDict:
    with _control_state_lock:
        if controller.type == ModbusControllerConnection.TYPE:
            assert isinstance(controller, ModbusControllerConnection)
            addresses: List[str] = split_addresses(controller.address)
            if len(addresses) > 0:
                result = _connect_modbus(
                    master_address=addresses[0],
                    slave_addresses=addresses[1:],
                    master_device_id=controller.master_device_id,
                    meter_device_id=controller.meter_device_id,
                    slave_device_id=controller.slave_device_id,
                )
                _control_state.settings_controller = controller
                _save_settings()
                LOGGER.info(f'{_LOG_SRC}Power controller connection: {json.dumps(result)}')
                return result
            else:
                LOGGER.warning(f'{_LOG_SRC}No addresses provided for modbus controller')
                raise ControlLoopError('no addresses provided for modbus controller')
        else:
            raise ControlLoopError('unknown controller type', errors={'type': controller.type})


def disconnect_controller() -> JSONDict:
    """
    Close the power controller connection.
    """
    with _control_state_lock:
        if _control_state.controller is not None:
            _control_state.controller.close()
            _control_state.reset_controller(None)
        _control_state.settings_controller = None
        return _control_state.power_controller_status


def connect_pricer(pricer: PricerConnection) -> JSONDict:
    with _control_state_lock:
        if pricer.type == AmberPricerConnection.TYPE:
            assert isinstance(pricer, AmberPricerConnection)
            api_token = pricer.api_token.strip()
            nmi = pricer.nmi.strip()
            if api_token != '' and nmi != '':
                result = _connect_amber(
                    api_token=api_token,
                    nmi=nmi,
                )
                _control_state.settings_pricer = pricer
                _save_settings()
                LOGGER.info(f'{_LOG_SRC}Power pricer connection: {json.dumps(result)}')
                return result
            else:
                LOGGER.warning(f'{_LOG_SRC}No API token or NMI provided for amber pricer')
                raise ControlLoopError('no API token or NMI provided for amber pricer')
        else:
            raise ControlLoopError('unknown pricer type', errors={'type': pricer.type})


def disconnect_pricer() -> JSONDict:
    """
    Close the power pricer connection.
    """
    with _control_state_lock:
        if _control_state.pricer is not None:
            _control_state.pricer.close()
            _control_state.reset_pricer(None)
        _control_state.settings_pricer = None
        return _control_state.power_pricer_status


def connect_car_charger(charger: ChargerConnection) -> JSONDict:
    with _control_state_lock:
        if charger.type == TeslaChargerConnection.TYPE:
            assert isinstance(charger, TeslaChargerConnection)
            result = _connect_tesla_wall_connector(address=charger.address)
            _control_state.settings_charger = charger
            _save_settings()
            LOGGER.info(f'{_LOG_SRC}Car charger connection: {json.dumps(result)}')
            return result
        else:
            raise ControlLoopError('unknown charger type', errors={'type': charger.type})


def disconnect_car_charger() -> JSONDict:
    """
    Close the power pricer connection.
    """
    with _control_state_lock:
        if _control_state.charger is not None:
            _control_state.charger.close()
            _control_state.reset_car_charger(None)
        _control_state.settings_charger = None
        return _control_state.car_charger_status


# =============================================================================
#  Support functions
# =============================================================================

def _connect_modbus(
        *,
        master_address: str,
        slave_addresses: Iterable[str] = (),
        master_device_id: int,
        meter_device_id: int,
        slave_device_id: int,
) -> JSONDict:
    """
    Establish a power controller modbus connection to the inverter.

    Args:
        master_address: MAC or IP address of the master inverter.
        slave_addresses: MAC or IP address of the slave inverters.
        master_device_id: Modbus device ID of the master inverter.
        meter_device_id: Modbus device ID of the meter.
        slave_device_id: Modbus device ID of the slave inverters.

    Raises:
        ControlLoopError: a connection cannot be established.
    """
    addresses: List[_Address] = _resolve_addresses([master_address] + list(slave_addresses))

    # get ModbusTcpClient objects
    clients: List[ModbusTcpClient] = []  # coindexed with address
    errors: List[JSONDict] = []
    for address in addresses:
        try:
            client = ModbusTcpClient(address.ip_address, port=502)
            client.connect()
            clients.append(client)
        except Exception as err:
            errors.append({
                'host': address.ip_address,
                'mac_address': address.mac_address,
                'error': str(err),
            })
    # Fail if there are any errors
    if len(errors) > 0:
        raise ControlLoopError('could not connect Modbus TCP client', errors=errors)

    # Configure power controller
    master_client: ModbusTcpClient = clients[0]
    slave_clients: List[ModbusTcpClient] = clients[1:]
    devices: Dict[str, ModbusDevice] = {
        'master': ModbusDevice(master_client, master_device_id),
    }
    slave_names: List[str]
    if len(slave_clients) == 1:
        slave_names = ['slave']
        devices['slave'] = ModbusDevice(slave_clients[0], slave_device_id)
    else:
        slave_names = []
        for slave_id, slave_client in enumerate(slave_clients, start=1):
            name = f'slave_{slave_id}'
            slave_names.append(name)
            devices[name] = ModbusDevice(slave_client, slave_device_id)
    devices['meter'] = ModbusDevice(master_client, meter_device_id)

    controller = ModbusPowerController(
        Modbus(devices),
        master='master',
        meter='meter',
        slaves=slave_names,
    )

    disconnect_controller()
    _control_state.reset_controller(controller)

    # Update the connection status record
    mac_addr_lookup: Dict[str, str] = {
        address.ip_address: address.mac_address
        for address in addresses
    }
    devices_record: JSONDict = {}
    for device_name, device in devices.items():
        host: str = device.client.comm_params.host
        mac_address: Optional[str] = mac_addr_lookup.get(host)
        device_record: JSONDict = {'host': host}
        if master_address is not None and mac_address != '':
            device_record['mac_address'] = mac_address
        device_record['device'] = device.device_id
        devices_record[device_name] = device_record
    _control_state.power_controller_status = {
        'status': 'Modbus connection',
        'devices': devices_record,
    }

    return _control_state.power_controller_status


def _connect_amber(*, api_token: str, nmi: str) -> JSONDict:
    """
    Establish a power pricer connection using Amber.

    Raises:
        ControlLoopError: a connection cannot be established.
    """
    try:
        amber_pricer = AmberPowerPricer(api_token, nmi)
    except Exception as err:
        _control_state.reset_pricer(None)
        raise ControlLoopError('could not connect Amber', errors=[str(err)])

    disconnect_pricer()
    _control_state.reset_pricer(amber_pricer)

    _control_state.power_pricer_status = {
        'status': 'Amber connection',
        'nmi': amber_pricer.nmi,
        'site': amber_pricer.site_id,
    }
    return _control_state.power_pricer_status


def _connect_tesla_wall_connector(*, address: str) -> JSONDict:
    """
    Establish a car charger connection using Tesla Wall Connector.

    Args:
        address: MAC or IP address of the Tesla Wall Connector.

    Raises:
        ControlLoopError: a connection cannot be established.
    """
    address: _Address = _resolve_addresses([address])[0]
    try:
        car_charger = TeslaWallConnector(address.ip_address)
    except Exception as err:
        _control_state.reset_pricer(None)
        raise ControlLoopError('could not connect Tesla Wall Connector', errors=[str(err)])

    disconnect_car_charger()
    _control_state.reset_car_charger(car_charger)

    _control_state.car_charger_status = {
        'status': 'Tesla Wall Connector connection',
        'host': address.ip_address,
    }
    if address.mac_address != '':
        _control_state.car_charger_status['mac_address'] = address.mac_address

    return _control_state.car_charger_status


@dataclass
class _Address:
    raw_address: str
    mac_address: str = ''
    ip_address: str = ''


def _resolve_addresses(raw_addresses: List[str]) -> List[_Address]:
    """
    Resolve a list of MAC or IP address.

    Args:
        raw_addresses: a list of MAC or IP addresses.

    Returns:
        the resolved address

    Raises:
        ControlLoopError: if any of the addresses are invalid
    """
    addresses: List[_Address] = [_Address(address) for address in raw_addresses]
    invalid_addresses: List[str] = []
    # Work out what address are MAC address
    found_mac_addresses: List[str] = []
    for address in addresses:
        raw_address = address.raw_address
        is_mac = ':' in raw_address
        is_ip = '.' in raw_address
        if is_mac and not is_ip:
            address.mac_address = raw_address
            found_mac_addresses.append(raw_address)
        elif is_ip and not is_mac:
            address.ip_address = raw_address
        else:
            invalid_addresses.append(raw_address)

    # Fail if there are any invalid addresses
    if len(invalid_addresses) > 0:
        raise ControlLoopError('invalid address', errors=invalid_addresses)

    # Look up IP address for MAC address
    mac_lookup: Dict[str, str] = find_ip_by_mac(found_mac_addresses)
    for address in addresses:
        if address.ip_address == '':
            mac_address = address.mac_address
            ip_address: Optional[str] = mac_lookup.get(mac_address)
            if ip_address is None:
                invalid_addresses.append(mac_address)
            else:
                address.ip_address = ip_address

    # Fail if there are any invalid ip addresses
    if len(invalid_addresses) > 0:
        raise ControlLoopError('could not find IP address for MAC address', errors=invalid_addresses)

    return addresses


def _update_listeners(
        status_listeners: List[StatusListener],
        registers_listeners: List[RegistersListener],
) -> None:
    """
    Call update on the listeners. No locking, no list copying.

    WARNING:
    This should be called while not holding the control state lock
    so that any listeners can be updated without blocking on the control loop.
    This means `_update_listeners` should be called on copies of the listener lists
    so incase there is an attempt to modify the control state while updating listeners.
    """
    if len(status_listeners) > 0:
        status = get_status()
        for status_listener in status_listeners:
            try:
                status_listener.update(status)
            except Exception as e:
                LOGGER.error(f'{_LOG_SRC}Error updating status listener: {status_listener!r}, error: {e}')
    if len(registers_listeners) > 0:
        registers = get_registers()
        for registers_listener in registers_listeners:
            registers_listener.update(registers)


def _force_price_check() -> None:
    """
    Force the control loop to perform a price check
    for price-based policies.
    """
    with _control_state_lock:
        state = _control_state
        state.next_buy_price_check = _MIN_DATE
        state.next_feed_in_price_check = _MIN_DATE


def _update_price() -> List[Price]:
    """
    Updates server state last_price and returns lookahead prices, in time order.
    """
    state = _control_state

    power_pricer = state.pricer
    if power_pricer is None:
        LOGGER.error(f'{_LOG_SRC}Price update not available. Power pricer not connected')
        return [state.last_price]

    prices = power_pricer.get_price(Constants.PRICE_LOOK_AHEAD // 5)
    price = prices[0]
    state.last_price = price
    LOGGER.info(f'{_LOG_SRC}Buy price update: {price.buy_price}')
    LOGGER.info(f'{_LOG_SRC}Feed-in price update: {price.feed_in_price}')
    return prices


def _update_price_check(prices: List[Price]) -> None:
    """
    Update next_feed_in_price_check and next_buy_price_check based on the lookahead prices.
    """
    state = _control_state
    _update_next_buy_price_check(prices, force_charging=(state.battery_mode == BatteryMode.FORCE_CHARGE))
    _update_next_feed_in_price_check(prices, zero_export=(state.inverter_mode == InverterMode.ZERO_EXPORT))


def _update_next_feed_in_price_check(prices: List[Price], zero_export: bool) -> None:
    """
    Update next_feed_in_price_check based on the lookahead prices.
    """
    state = _control_state
    end: int = len(prices) - 1

    # If zero export, no need to check the feed-in price if:
    #     feed-in price > enable_export_price_threshold - _ENABLE_FEED_IN_TOLERANCE
    # If not zero export, no need to check the feed-in price if:
    #     feed-in price < disable_export_price_threshold + _DISABLE_FEED_IN_TOLERANCE
    last_safe_feed_in: int = 0
    enable_export_threshold: float = state.enable_export_price_threshold - Constants.ENABLE_FEED_IN_TOLERANCE
    disable_export_threshold: float = state.disable_export_price_threshold + Constants.DISABLE_FEED_IN_TOLERANCE

    def safe() -> bool:
        if zero_export:
            return prices[last_safe_feed_in].feed_in_price < enable_export_threshold
        else:
            return prices[last_safe_feed_in].feed_in_price > disable_export_threshold

    while last_safe_feed_in < end and safe():
        last_safe_feed_in += 1

    state.next_feed_in_price_check = _next_price_check(prices[last_safe_feed_in])
    LOGGER.info(f'{_LOG_SRC}Next feed-in price check: {state.next_feed_in_price_check}')


def _update_next_buy_price_check(prices: List[Price], force_charging: bool) -> None:
    """
    Update next_buy_price_check based on the lookahead prices.
    """
    state = _control_state
    end: int = len(prices) - 1

    # If force charging, no need to check the feed-in price if:
    #     buy price < stop_charge_price_threshold - _STOP_BUY_TOLERANCE
    # If not force charging, no need to check the feed-in price if:
    #     buy price > start_charge_price_threshold + _START_BUY_TOLERANCE
    last_safe_buy: int = 0
    stop_charge_threshold: float = state.stop_charge_price_threshold - Constants.START_BUY_TOLERANCE
    start_charge_threshold: float = state.start_charge_price_threshold + Constants.STOP_BUY_TOLERANCE

    def safe() -> bool:
        if force_charging:
            return prices[last_safe_buy].buy_price < stop_charge_threshold
        else:
            return prices[last_safe_buy].buy_price > start_charge_threshold

    while last_safe_buy < end and safe():
        last_safe_buy += 1

    state.next_buy_price_check = _next_price_check(prices[last_safe_buy])

    LOGGER.info(f'{_LOG_SRC}Next buy price check: {state.next_buy_price_check}')


def _next_price_check(price: Price) -> datetime:
    """
    The given price record is selected as the actual or forecast record when a policy-driven price check.
    Based on that record, when should the next price check be performed for the policy?
    """
    if price.estimate:
        delay = timedelta(seconds=Constants.PRICE_SETTLE_CHECK)
        return min(datetime.now(UTC) + delay, price.end_time)
    else:
        return price.end_time


def _save_settings() -> None:
    """
    This is called when the user settings are changed. We persist the settings
    so that they are available across restarts.
    """
    with _control_state_lock:
        settings_path = _control_state.settings_path
        if settings_path is not None:
            try:
                with open(settings_path, 'w') as file:
                    settings: Settings = get_settings()
                    print(settings.model_dump_json(), file=file)
            except Exception as e:
                LOGGER.error(f'{_LOG_SRC}Error saving settings: {e}')


def _load_settings() -> bool:
    """
    Load the persisted settings.

    Returns:
        True if settings were loaded successfully, False otherwise.
    """
    with _control_state_lock:
        settings_path = _control_state.settings_path
        if settings_path is not None:
            try:
                with open(settings_path, 'r') as file:
                    json_string = file.read()
                settings = Settings.model_validate_json(json_string)
                configure_from_settings(settings)
                return True
            except Exception as e:
                LOGGER.error(f'{_LOG_SRC}Error loading settings: {e}')
        return False
