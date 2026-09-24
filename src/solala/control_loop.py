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
DEFAULT_START_CHARGE_PRICE_THRESHOLD: float = 10  # charge battery below this price
DEFAULT_STOP_CHARGE_PRICE_THRESHOLD: float = 11  # re-enable export above this price

DATE_FORMAT = '%Y-%m-%d %H:%M:%S (%Z)'  # format for human-readable timestamps

_LOG_SRC = 'control_loop'  # prefix for log messages
_LOOP_SLEEP: int = 5  # number of seconds to sleep between loop iterations
_CONTROL_DURATION: int = 11  # number of seconds a control remains active
_PRICE_LOOK_AHEAD: int = 0#####DEBUG 60  # number of minutes to look ahead (should be a multiple of 5)
_DISABLE_FEED_IN_TOLERANCE: float = 2.0  # cents, a feed-in power price tolerance for price lookahead
_ENABLE_FEED_IN_TOLERANCE: float = 2.0  # cents, a feed-in power price tolerance for price lookahead
_STOP_BUY_TOLERANCE: float = 2.0  # cents, a buy power price tolerance for price lookahead
_START_BUY_TOLERANCE: float = 2.0  # cents, a buy power price tolerance for price lookahead

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


class ExportMode(Enum):
    UNKNOWN = auto()  # The inverter has not been configured by the control loop yet
    ENABLE = auto()  # The inverter is configured for normal operation for grid import and export
    DISABLE = auto()  # The inverter is configured to minimise export to the grid


class BatteryPolicy(Enum):
    MANUAL = auto()
    CHEAP_CHARGE = auto()


class ExportPolicy(Enum):
    MANUAL = auto()
    NEG_FEED_IN_DISABLE = auto()


@dataclass
class _ControlState:
    power_controller: Optional[PowerController]
    power_pricer: Optional[PowerPricer]
    battery_mode: BatteryMode = BatteryMode.UNKNOWN
    export_mode: ExportMode = ExportMode.UNKNOWN
    battery_policy: BatteryPolicy = BatteryPolicy.MANUAL
    export_policy: ExportPolicy = ExportPolicy.MANUAL

    last_price: Price = _NO_PRICE
    next_feed_in_price_check: datetime = _MIN_DATE
    next_buy_price_check: datetime = _MIN_DATE

    # NEG_FEED_IN_DISABLE parameters
    disable_export_price_threshold: float = DEFAULT_DISABLE_FEED_IN_PRICE_THRESHOLD
    enable_export_price_threshold: float = DEFAULT_ENABLE_FEED_IN_PRICE_THRESHOLD

    # CHEAP_CHARGE parameters
    start_charge_price_threshold: float = DEFAULT_START_CHARGE_PRICE_THRESHOLD
    stop_charge_price_threshold: float = DEFAULT_STOP_CHARGE_PRICE_THRESHOLD

    def reset_controller(self, controller: Optional[PowerController]) -> None:
        self.power_controller = controller
        self.battery_mode = BatteryMode.UNKNOWN
        self.export_mode = ExportMode.UNKNOWN
        self.export_policy = ExportPolicy.MANUAL
        self.last_price: Price = _NO_PRICE

        self.next_feed_in_price_check = _MIN_DATE
        self.next_buy_price_check = _MIN_DATE


# Global server state variable
_control_state: _ControlState = _ControlState(None, None)
_control_state_lock = threading.RLock()
_control_loop_running: bool = True  # set as False to terminate the control loop


def control_loop() -> None:
    """
    The control loop is an infinite loop to implement the
    control logic of the battery and export modes and policies.

    Multiple thread-safe functions are provided to manage the
    behaviour of the control loop.

    Call `exit_control_loop()` to gracefully terminate the control loop.
    """
    prev_state: _ControlState = _ControlState(None, None)

    while _control_loop_running:
        with _control_state_lock:
            state = _control_state

            if state.power_controller is None:
                prev_state.power_controller = None
                time.sleep(_LOOP_SLEEP)
                continue
            if prev_state.power_controller is not state.power_controller:
                # Assume the same power_controller with unknown state.
                prev_state.power_pricer = state.power_pricer
                prev_state.reset_controller(state.power_controller)
            power_controller = state.power_controller
            assert power_controller is not None

            # Battery Policy - may change state.battery_mode
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
            if prev_state.battery_mode != state.battery_mode:
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

            # Export Policy - may change state.export_mode
            if state.export_policy == ExportPolicy.NEG_FEED_IN_DISABLE:
                if state.next_feed_in_price_check <= datetime.now(UTC):
                    # time to check the price again
                    prices = _update_price()
                    price = state.last_price
                    feed_in_price = price.feed_in_price
                    if feed_in_price < state.disable_export_price_threshold:
                        state.export_mode = ExportMode.DISABLE
                    elif feed_in_price > state.disable_export_price_threshold:
                        state.export_mode = ExportMode.ENABLE
                    _update_price_check(prices)

            # Export Mode
            if prev_state.export_mode != state.export_mode:
                match state.export_mode:
                    case ExportMode.ENABLE:
                        power_controller.enable_export()
                    case ExportMode.DISABLE:
                        pass  # Handled below
                prev_state.export_mode = state.export_mode

            if prev_state.export_mode == ExportMode.DISABLE:
                try:
                    power_controller.disable_export(change_duration=_CONTROL_DURATION)
                except Exception as e:
                    LOGGER.error(f'[{_LOG_SRC}] Error processing command: disable_export. Error: {e}')

        # Server state unlocked
        # Slow the loop down to keep the network and inverters from being overwhelmed
        time.sleep(_LOOP_SLEEP)


# =============================================================================
#  Control loop interaction
# =============================================================================

def get_control_status() -> JSONDict:
    with _control_state_lock:
        battery: JSONDict = {
            'mode': _control_state.battery_mode.name,
            'policy': _control_state.battery_policy.name,
        }
        export: JSONDict = {
            'mode': _control_state.export_mode.name,
            'policy': _control_state.export_policy.name,
        }
        if _control_state.battery_policy == BatteryPolicy.CHEAP_CHARGE:
            battery.update({
                'next_buy_price_check': _control_state.next_buy_price_check.strftime(DATE_FORMAT),
                'start_charge_price_threshold': _control_state.start_charge_price_threshold,
                'stop_charge_price_threshold': _control_state.stop_charge_price_threshold,
            })
        if _control_state.export_policy == ExportPolicy.NEG_FEED_IN_DISABLE:
            export.update({
                'next_feed_in_price_check': _control_state.next_feed_in_price_check.strftime(DATE_FORMAT),
                'disable_export_price_threshold': _control_state.disable_export_price_threshold,
                'enable_export_price_threshold': _control_state.enable_export_price_threshold,
            })

        return {
            'battery': battery,
            'export': export,
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
            'battery': {
                'start_charge_price_threshold': state.start_charge_price_threshold,
                'stop_charge_price_threshold': state.stop_charge_price_threshold,
            },
            'export': {
                'disable_export_price_threshold': state.disable_export_price_threshold,
                'enable_export_price_threshold': state.enable_export_price_threshold,
            }
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
            LOGGER.error(f'Price update not available. Error: power_price not connected')
        elif price.end_time <= datetime.now(UTC):
            try:
                price: Price = _control_state.power_pricer.get_price(0)[0]
                _control_state.last_price = price
            except (JSONDecodeError, IOError) as err:
                LOGGER.error(f'Price update not available. Error: {err}')
    return price


def set_control(
        *,
        battery_mode: Optional[BatteryMode] = None,
        export_mode: Optional[ExportMode] = None,
        battery_policy: Optional[BatteryPolicy] = None,
        export_policy: Optional[ExportPolicy] = None
) -> JSONDict:
    with _control_state_lock:
        state = _control_state

        if battery_mode is not None:
            state.battery_mode = battery_mode
        if export_mode is not None:
            state.export_mode = export_mode
        if battery_policy is not None:
            state.battery_policy = battery_policy
        if export_policy is not None:
            state.export_policy = export_policy

        _force_price_check()
        return get_control_status()


def set_parameters(
        *,
        # NEG_FEED_IN_DISABLE parameters
        disable_export_price_threshold: Optional[float] = None,
        enable_export_price_threshold: Optional[float] = None,
        # CHEAP_CHARGE parameters
        start_charge_price_threshold: Optional[float] = None,
        stop_charge_price_threshold: Optional[float] = None,
) -> JSONDict:
    """
    Set the price threshold for the battery and export policies.
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
    Establish a power control modbus connection to the inverter.
    """
    with _control_state_lock:
        all_addresses: List[str] = [master_address] + list(slave_addresses)
        all_mac_addresses: List[Optional[str]] = []
        found_mac_addresses: List[str] = []
        invalid_addresses: List[str] = []
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
        if len(invalid_addresses) > 0:
            return {
                'connect_modbus': 'Error: invalid address',
                'addresses': invalid_addresses
            }

        # Look up IP addresses for MAC addresses, only if there are MAC addresses to look up
        mac_lookup: Dict[str, str] = find_ip_by_mac(found_mac_addresses)

        all_clients: List[ModbusTcpClient] = []
        for i in range(len(all_addresses)):
            mac_address = all_mac_addresses[i]
            if mac_address is None:
                ip_address = all_addresses[i]
            else:
                ip_address: Optional[str] = mac_lookup.get(mac_address)
                if ip_address is None:
                    return {
                        'connect_modbus': 'Error: IP address not found.',
                        'mac_address': mac_address,
                    }
            all_clients.append(ModbusTcpClient(ip_address))
        if len(invalid_addresses) > 0:
            return {
                'connect_modbus': 'Error: could not find ip address for mac address',
                'addresses': invalid_addresses
            }

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

        modbus: Modbus = Modbus(devices)
        controller = ModbusPowerController(
            modbus,
            master='master',
            meter='meter',
            slaves=slave_names,
        )
        _control_state.reset_controller(controller)

        result = {
            'connect_modbus': 'Success',
            'devices': {
                device_name: {
                    'device_id': device.device_id,
                    'host': device.client.comm_params.host,
                }
                for device_name, device in devices.items()
            },
            'mac_addresses': mac_lookup,
        }
        return result


def disconnect_control() -> JSONDict:
    """
    Close the power control connection.
    """
    with _control_state_lock:
        if _control_state.power_controller is None:
            return {'disconnect_control': 'already disconnected'}
        else:
            _control_state.power_controller.close()
            _control_state.reset_controller(None)
            return {'disconnect_control': 'Success'}


def connect_amber(api_token: str, nmi: str) -> JSONDict:
    """
    Establish a power price connection using Amber.
    """
    with _control_state_lock:
        amber_pricer = AmberPowerPricer(api_token, nmi)
        _control_state.power_pricer = amber_pricer
        return {
            'connect_amber': 'Success',
            'site_id': amber_pricer.site_id,
        }


def disconnect_price() -> JSONDict:
    """
    Close the power control price connection.
    """
    with _control_state_lock:
        if _control_state.power_pricer is None:
            return {'disconnect_price': 'already disconnected'}
        _control_state.power_pricer = None
        return {'disconnect_price': 'Success'}


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
        LOGGER.error(f'[{_LOG_SRC}] Price update not available. Power pricer not connected')
        return [state.last_price]

    prices = power_pricer.get_price(_PRICE_LOOK_AHEAD // 5)
    price = prices[0]
    state.last_price = price
    LOGGER.info(f'[{_LOG_SRC}] Price update, buy: {price.buy_price}')
    LOGGER.info(f'[{_LOG_SRC}] Price update, feed-in: {price.feed_in_price}')
    return prices


def _update_price_check(prices: List[Price]) -> None:
    """
    Update next_feed_in_price_check and next_buy_price_check based on the lookahead prices.
    """
    state = _control_state
    _update_next_buy_price_check(prices, force_charging=(state.battery_mode == BatteryMode.FORCE_CHARGE))
    _update_next_feed_in_price_check(prices, export_enabled=(state.export_mode == ExportMode.ENABLE))


def _update_next_feed_in_price_check(prices: List[Price], export_enabled: bool) -> None:
    """
    Update next_feed_in_price_check based on the lookahead prices.
    """
    state = _control_state
    end: int = len(prices) - 1

    # If export enabled, no need to check the feed-in price if:
    #     feed-in price < disable_export_price_threshold + _DISABLE_FEED_IN_TOLERANCE
    # If export disabled, no need to check the feed-in price if:
    #     feed-in price > enable_export_price_threshold - _ENABLE_FEED_IN_TOLERANCE
    last_safe_feed_in: int = 0
    disable_export_threshold: float = state.disable_export_price_threshold + _DISABLE_FEED_IN_TOLERANCE
    enable_export_threshold: float = state.enable_export_price_threshold - _ENABLE_FEED_IN_TOLERANCE

    def safe() -> bool:
        if export_enabled:
            return prices[last_safe_feed_in].feed_in_price > disable_export_threshold
        else:
            return prices[last_safe_feed_in].feed_in_price < enable_export_threshold

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
    stop_charge_threshold: float = state.stop_charge_price_threshold - _START_BUY_TOLERANCE
    start_charge_threshold: float = state.start_charge_price_threshold + _STOP_BUY_TOLERANCE

    def safe() -> bool:
        if force_charging:
            return prices[last_safe_buy].buy_price < stop_charge_threshold
        else:
            return prices[last_safe_buy].buy_price > start_charge_threshold

    while last_safe_buy < end and safe():
        last_safe_buy += 1

    state.next_buy_price_check = prices[last_safe_buy].end_time

    LOGGER.info(f'[{_LOG_SRC}] next buy price check: {state.next_buy_price_check}')
