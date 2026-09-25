import threading
import time
from dataclasses import dataclass
from datetime import datetime, UTC
from enum import Enum, auto
from json import JSONDecodeError
from typing import Optional, List, Iterable, Dict

from pymodbus.client import ModbusTcpClient

from solala.log import LOGGER
from solala.power_controller.impl_modbus.modbus import Modbus, ModbusDevice
from solala.power_controller.impl_modbus.modbus_power_controller import PowerController, ModbusPowerController
from solala.power_pricer.impl_amber.amber_power_pricer import Price, AmberPowerPricer
from solala.power_pricer.power_pricer import PowerPricer
from solala.utils.json import JSONDict
from solala.utils.network import find_ip_by_mac

DEFAULT_DISABLE_FEED_IN_PRICE_THRESHOLD: float = -0.1  # disable export below this price
DEFAULT_ENABLE_FEED_IN_PRICE_THRESHOLD: float = 0.1  # re-enable export above this price
DEFAULT_START_CHARGE_PRICE_THRESHOLD: float = 10  # start force charging below this price
DEFAULT_STOP_CHARGE_PRICE_THRESHOLD: float = 11  # stop force charging above this price

DATE_FORMAT = '%Y-%m-%d %H:%M:%S (%Z)'  # format for human-readable timestamps

_LOG_SRC = 'control_loop'  # prefix for log messages

_MIN_DATE = datetime.min.replace(tzinfo=UTC)
_NO_PRICE = Price(
    start_time=_MIN_DATE,
    end_time=_MIN_DATE,
    renewables=0,
    buy_price=0,
    feed_in_price=0,
)


class BatteryMode(Enum):
    UNKNOWN = auto()  # The battery has not been configured by the control loop yet
    ENABLE = auto()  # The battery is configured for normal operation, charge and discharge
    DISABLE = auto()  # The battery is logically disconnected, no charge or discharge
    FORCE_CHARGE = auto()  # The battery is configured to force charge to its maximum charge
    FORCE_DISCHARGE = auto()  # The battery is configured to force discharge to its minimum charge


class InverterMode(Enum):
    UNKNOWN = auto()  # The inverter has not been configured by the control loop yet
    ENABLE = auto()  # The inverter is configured for normal operation for grid import and export
    DISABLE = auto()  # The inverter is configured to not produce power
    ZERO_EXPORT = auto()  # The inverter is controlled to minimise export to the grid


class BatteryPolicy(Enum):
    MANUAL = auto()
    CHEAP_CHARGE = auto()  # set battery mode to FORCE_CHARGE if power buy price is low


class InverterPolicy(Enum):
    MANUAL = auto()
    NEG_FEED_IN_ZERO_EXPORT = auto()  # set inverter mode to ZERO_EXPORT if feed-in price is negative


class Constants:
    """
    These constants control the behaviour of the control loop.
    They should only be modified by developers for testing and debugging.
    """
    LOOP_SLEEP: int = 5  # number of seconds to sleep between loop iterations
    CONTROL_DURATION: int = 11  # number of seconds a control remains active
    PRICE_LOOK_AHEAD: int = 60  # number of minutes to look ahead (should be a multiple of 5)
    DISABLE_FEED_IN_TOLERANCE: float = 2.0  # cents, a feed-in power price tolerance for price lookahead
    ENABLE_FEED_IN_TOLERANCE: float = 2.0  # cents, a feed-in power price tolerance for price lookahead
    STOP_BUY_TOLERANCE: float = 2.0  # cents, a buy power price tolerance for price lookahead
    START_BUY_TOLERANCE: float = 2.0  # cents, a buy power price tolerance for price lookahead

    @staticmethod
    def as_dict() -> JSONDict:
        return {
            'LOOP_SLEEP': Constants.LOOP_SLEEP,
            'CONTROL_DURATION': Constants.CONTROL_DURATION,
            'PRICE_LOOK_AHEAD': Constants.PRICE_LOOK_AHEAD,
            'DISABLE_FEED_IN_TOLERANCE': Constants.DISABLE_FEED_IN_TOLERANCE,
            'ENABLE_FEED_IN_TOLERANCE': Constants.ENABLE_FEED_IN_TOLERANCE,
            'STOP_BUY_TOLERANCE': Constants.STOP_BUY_TOLERANCE,
            'START_BUY_TOLERANCE': Constants.START_BUY_TOLERANCE,
        }


@dataclass
class _ControlState:
    power_controller: Optional[PowerController]
    power_pricer: Optional[PowerPricer]

    battery_mode: BatteryMode = BatteryMode.UNKNOWN
    inverter_mode: InverterMode = InverterMode.UNKNOWN
    battery_policy: BatteryPolicy = BatteryPolicy.MANUAL
    inverter_policy: InverterPolicy = InverterPolicy.MANUAL

    last_price: Price = _NO_PRICE
    next_feed_in_price_check: datetime = _MIN_DATE
    next_buy_price_check: datetime = _MIN_DATE

    # NEG_FEED_IN_ZERO_EXPORT parameters
    disable_export_price_threshold: float = DEFAULT_DISABLE_FEED_IN_PRICE_THRESHOLD
    enable_export_price_threshold: float = DEFAULT_ENABLE_FEED_IN_PRICE_THRESHOLD

    # CHEAP_CHARGE parameters
    start_charge_price_threshold: float = DEFAULT_START_CHARGE_PRICE_THRESHOLD
    stop_charge_price_threshold: float = DEFAULT_STOP_CHARGE_PRICE_THRESHOLD

    def reset_controller(self, controller: Optional[PowerController]) -> None:
        self.power_controller = controller
        self.battery_mode = BatteryMode.UNKNOWN
        self.inverter_mode = InverterMode.UNKNOWN
        self.inverter_policy = InverterPolicy.MANUAL
        self.last_price: Price = _NO_PRICE

        self.next_feed_in_price_check = _MIN_DATE
        self.next_buy_price_check = _MIN_DATE

    def reset_pricer(self, pricer: Optional[PowerPricer]) -> None:
        self.power_pricer = pricer
        self.last_price: Price = _NO_PRICE
        self.next_feed_in_price_check: datetime = _MIN_DATE
        self.next_buy_price_check: datetime = _MIN_DATE


# Global server state variables
_control_state: _ControlState = _ControlState(None, None)
_control_state_lock = threading.RLock()
_control_loop_running: bool = True  # set as False to terminate the control loop
_power_controller_status: JSONDict = {'status': 'disconnected'}
_power_pricer_status: JSONDict = {'status': 'disconnected'}


def control_loop() -> None:
    """
    The control loop is an infinite loop to implement the
    control logic of the battery and inverter modes and policies.

    Multiple thread-safe functions are provided to manage the
    behaviour of the control loop.

    Call `exit_control_loop()` to gracefully terminate the control loop.
    """
    prev_state: _ControlState = _ControlState(None, None)

    while _control_loop_running:
        control_step(_control_state, prev_state)
        # Server state unlocked
        # Slow the loop down to keep the network and inverters from being overwhelmed
        time.sleep(Constants.LOOP_SLEEP)


def control_step(state: _ControlState, prev_state: _ControlState) -> None:
    """
    Perform one functional step of the control loop.
    This function will grab the control state lock.
    No work is performed if the power controller is None.
    No non-manual policies are performed if the power pricer is None.

    Args:
        state: the current control state
        prev_state: the previous control state
    """
    with _control_state_lock:
        if state.power_controller is None:
            prev_state.power_controller = None
            time.sleep(Constants.LOOP_SLEEP)
            return

        if prev_state.power_controller is not state.power_controller:
            # Assume the same power_controller with unknown state.
            prev_state.power_pricer = state.power_pricer
            prev_state.reset_controller(state.power_controller)
        power_controller = state.power_controller
        assert power_controller is not None

        # Battery Policy - may change Battery Mode
        if state.power_pricer is not None:
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
        if state.power_pricer is not None:
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
            LOGGER.error(f'[{_LOG_SRC}] Error processing command: {prev_state.inverter_mode}. Error: {e}')


# =============================================================================
#  Control loop interaction
# =============================================================================

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
        if _control_state.power_pricer is None:
            return {'error': 'power pricer not connected'}
        cur_price: Price = get_cur_price()
        result = cur_price.as_dict(DATE_FORMAT)
        return result


def get_power_status() -> JSONDict:
    with _control_state_lock:
        if _control_state.power_controller is None:
            return {'error': 'power controller not connected'}
        result = _control_state.power_controller.get_status().as_dict()
        return result


def get_connection_status() -> JSONDict:
    with _control_state_lock:
        return {
            'controller': _power_controller_status,
            'pricer': _power_pricer_status,
        }


def get_status() -> JSONDict:
    with _control_state_lock:
        return {
            'control': get_control_status(),
            'price': get_price_status(),
            'power': get_power_status(),
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


def get_registers() -> JSONDict:
    with _control_state_lock:
        state = _control_state
        if state.power_controller is None:
            return {'error': 'power controller not connected'}
        else:
            return {
                register: value
                for register, value in state.power_controller.get_registers()
            }


def get_cur_price() -> Price:
    with _control_state_lock:
        price = _control_state.last_price
        if _control_state.power_pricer is None:
            LOGGER.error(f'price update not available. Error: power_price not connected')
        elif price.end_time <= datetime.now(UTC):
            try:
                price: Price = _control_state.power_pricer.get_price(0)[0]
                _control_state.last_price = price
            except (JSONDecodeError, IOError) as err:
                LOGGER.error(f'price update not available. Error: {err}')
    return price


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
            return {'error': 'export price threshold: disable must be less than enable'}
        if start_charge_price_threshold >= stop_charge_price_threshold:
            return {'error': 'charge price threshold: start must be less than stop'}

        state.disable_export_price_threshold = disable_export_price_threshold
        state.enable_export_price_threshold = enable_export_price_threshold
        state.start_charge_price_threshold = start_charge_price_threshold
        state.stop_charge_price_threshold = stop_charge_price_threshold

        _force_price_check()
        return get_parameters()


def exit_control_loop() -> None:
    """
    Flag to exit the control loop on the next iteration.
    """
    global _control_loop_running
    with _control_state_lock:
        _control_loop_running = False


# =============================================================================
#  Connection management for power control and price
# =============================================================================

def connect_modbus(
        master_address: str,
        slave_addresses: Iterable[str] = (),
        *,
        master_device_id: int = 1,
        meter_device_id: int = 200,
        slave_device_id: int = 1,
) -> JSONDict:
    """
    Establish a power controller modbus connection to the inverter.
    """
    global _power_controller_status
    with _control_state_lock:
        all_addresses: List[str] = [master_address] + list(slave_addresses)
        invalid_addresses: List[str] = []

        # Work out what addresses are MAC addresses
        all_mac_addresses: List[Optional[str]] = []  # coindexed with all_addresses
        found_mac_addresses: List[str] = []
        for address in all_addresses:
            is_mac = ':' in address
            is_ip = '.' in address
            if is_mac and not is_ip:
                all_mac_addresses.append(address)
                found_mac_addresses.append(address)
            elif is_ip and not is_mac:
                all_mac_addresses.append(None)
            else:
                invalid_addresses.append(address)

        # Fail if there are any invalid addresses
        if len(invalid_addresses) > 0:
            _power_controller_status = {
                'status': 'disconnected',
                'error': 'invalid address',
                'addresses': invalid_addresses,
            }
            return _power_controller_status

        # Look up IP addresses for MAC addresses
        all_ip_addresses: List[str] = []  # coindexed with all_addresses
        mac_lookup: Dict[str, str] = find_ip_by_mac(found_mac_addresses)
        for i in range(len(all_addresses)):
            mac_address = all_mac_addresses[i]
            if mac_address is None:
                all_ip_addresses.append(all_addresses[i])
            else:
                ip_address: Optional[str] = mac_lookup.get(mac_address)
                if ip_address is None:
                    invalid_addresses.append(mac_address)
                else:
                    all_ip_addresses.append(ip_address)

        # Fail if there are any invalid ip addresses
        if len(invalid_addresses) > 0:
            _power_controller_status = {
                'status': 'disconnected',
                'error': 'could not find ip address for mac address',
                'addresses': invalid_addresses,
            }
            return _power_controller_status

        # get ModbusTcpClient objects
        all_clients: List[ModbusTcpClient] = []  # coindexed with all_addresses
        errors: List[JSONDict] = []  # coindexed with all_addresses
        ip_address: str
        for i, ip_address in enumerate(all_ip_addresses):
            try:
                client = ModbusTcpClient(ip_address, port=502)
                client.connect()
                all_clients.append(client)
            except (IOError, TypeError, ValueError) as err:
                errors.append({
                    'host': ip_address,
                    'mac_address': all_mac_addresses[i],
                    'error': str(err),
                })

        # Fail if there are any errors
        if len(errors) > 0:
            _power_controller_status = {
                'status': 'disconnected',
                'error': 'could not connect Modbus TCP client',
                'messages': errors,
            }
            return _power_controller_status

        # Configure power controller
        master_client: ModbusTcpClient = all_clients[0]
        slave_clients: List[ModbusTcpClient] = all_clients[1:]
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
        _control_state.reset_controller(controller)

        # Update the connection status record
        _power_controller_status = {
            'status': 'Modbus connection',
            'devices': {
                device_name: {
                    'host': device.client.comm_params.host,
                    'device': device.device_id,
                }
                for device_name, device in devices.items()
            },
        }
        if len(mac_lookup) > 0:
            # noinspection PyTypeChecker
            _power_controller_status['mac_addresses'] = mac_lookup
        return _power_controller_status


def disconnect_control() -> JSONDict:
    """
    Close the power controller connection.
    """
    global _power_controller_status
    with _control_state_lock:
        if _control_state.power_controller is not None:
            _control_state.power_controller.close()
            _control_state.reset_controller(None)
            _power_controller_status = {'status': 'disconnected'}
        return _power_controller_status


def connect_amber(api_token: str, nmi: str) -> JSONDict:
    """
    Establish a power pricer connection using Amber.
    """
    global _power_pricer_status
    with _control_state_lock:
        try:
            amber_pricer = AmberPowerPricer(api_token, nmi)
        except (IOError, TypeError, ValueError) as err:
            _control_state.reset_pricer(None)
            _power_pricer_status = {
                'status': 'disconnected',
                'error': str(err),
            }
            return _power_pricer_status
        _control_state.reset_pricer(amber_pricer)
        _power_pricer_status = {
            'status': 'Amber connection',
            'nmi': amber_pricer.nmi,
            'site': amber_pricer.site_id,
        }
        return _power_pricer_status


def disconnect_price() -> JSONDict:
    """
    Close the power pricer connection.
    """
    global _power_pricer_status
    with _control_state_lock:
        if _control_state.power_pricer is not None:
            _control_state.power_pricer.close()
            _control_state.power_pricer = None
            _power_pricer_status = {'status': 'disconnected'}
        return _power_pricer_status


# =============================================================================
#  Support functions
# =============================================================================


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

    power_pricer = state.power_pricer
    if power_pricer is None:
        LOGGER.error(f'[{_LOG_SRC}] price update not available. Power pricer not connected')
        return [state.last_price]

    prices = power_pricer.get_price(Constants.PRICE_LOOK_AHEAD // 5)
    price = prices[0]
    state.last_price = price
    LOGGER.info(f'[{_LOG_SRC}] buy price update: {price.buy_price}')
    LOGGER.info(f'[{_LOG_SRC}] feed-in price update: {price.feed_in_price}')
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

    state.next_feed_in_price_check = prices[last_safe_feed_in].end_time
    LOGGER.info(f'[{_LOG_SRC}] next feed-in price check: {state.next_feed_in_price_check}')


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

    state.next_buy_price_check = prices[last_safe_buy].end_time

    LOGGER.info(f'[{_LOG_SRC}] next buy price check: {state.next_buy_price_check}')
