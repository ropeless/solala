import asyncio
import json
import math
import re
from collections.abc import AsyncIterator, Iterable, Iterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field, fields, Field
from datetime import datetime, UTC, date
from functools import partial
from inspect import getmembers
from pathlib import Path
from typing import get_type_hints, Any

from psycopg import DatabaseError
from pymodbus.client import ModbusTcpClient

from solala.constants import Constants, GUI_TIMESTAMP_FORMAT
from solala.control_loop.control_health import ControlHealth, HealthIssue, Severity
from solala.control_loop.errors import ControlLoopError
from solala.control_loop.loop_listener import LoopListener
from solala.control_loop.modes_and_policies import BatteryMode, InverterMode, BatteryPolicy, InverterPolicy, ControlMode
from solala.control_loop.resolve_addresses import ResolvedAddress, resolve_addresses
from solala.database.solala_database import SolalaDatabase, Measurement
from solala.database.solala_database_connections import SolalaDatabaseConnections
from solala.delegates.power_consumer.dummy_power_consumer.dummy_power_consumer import DummyPowerConsumer
from solala.delegates.power_consumer.power_consumer import PowerConsumer, ConsumerStatus
from solala.delegates.power_consumer.tesla_wall_connector.tesla_wall_connector import TeslaWallConnector
from solala.delegates.power_consumer.tuya_power_consumer.tuya_power_consumer import TuyaPowerConsumer
from solala.delegates.power_controller.dummy_power_controller.dummy_power_controller import DummyPowerController
from solala.delegates.power_controller.modbus_power_controller.modbus import Modbus, ModbusDevice
from solala.delegates.power_controller.modbus_power_controller.modbus_power_controller import ModbusPowerController
from solala.delegates.power_controller.power_controller import PowerController
from solala.delegates.power_controller.power_controller import PowerStatus
from solala.delegates.power_pricer.amber_power_pricer.amber_power_pricer import AmberPowerPricer
from solala.delegates.power_pricer.dummy_power_pricer.dummy_power_pricer import DummyPowerPricer
from solala.delegates.power_pricer.power_pricer import PowerPricer
from solala.delegates.power_pricer.price import Price
from solala.delegates.solar_forecaster.dummy_solar_forecaster.dummy_solar_forecaster import DummySolarForecaster
from solala.delegates.solar_forecaster.open_meteo_forecaster.open_meteo_forecaster import OpenMeteoForecaster
from solala.delegates.solar_forecaster.solar_forecast import SolarForecast
from solala.delegates.solar_forecaster.solar_forecaster import SolarForecaster, DailySolarForecast
from solala.delegates.solar_forecaster.weather_code import WeatherCode
from solala.logger import LOGGER
from solala.register import Register, RegisterType, RegisterValue, CallRegister, ReadOnlyRegister, check_type
from solala.register_bank import RegisterBank, EMPTY_REGISTER_BANK
from solala.settings import Settings, AmberPricerConnection, ModbusControllerConnection, TeslaWallConnectorConnection, \
    ControllerConnection, PricerConnection, ConsumerConnection, DummyControllerConnection, DummyPricerConnection, \
    DummyConsumerConnection, ForecasterConnection, OpenMeteoConnection, DummySolarForecasterConnection, \
    DatabaseConnection, TuyaConnection
from solala.utils.json_extras import JSONDict, json_num, JSONValue
from solala.utils.lifecycle_cache import LifecycleCache, LifecycleReturn, error, interim, valid
from solala.utils.ordered_async_rlock import OrderedAsyncRLock
from solala.utils.string_extras import split_addresses
from solala.utils.time_extras import now, local_time_zone

_MIN_DATE = datetime.min.replace(tzinfo=UTC)
_NO_POWER = PowerStatus(
    state_of_charge=0,
    power_limit=0,
    grid_power=0,
    solar_power=0,
    battery_power=0,
    house_power=0,
    accumulated_grid_energy_export=0,
    accumulated_grid_energy_import=0,
    accumulated_solar_energy=0,
    accumulated_battery_energy_charge=0,
    accumulated_battery_energy_discharge=0,
)
_NO_PRICE = Price(
    start_time=_MIN_DATE,
    end_time=_MIN_DATE,
    renewables=0,
    buy_price=0,
    feed_in_price=0,
    is_estimate=True,
)
_NO_FORECAST = SolarForecast(
    start_time=_MIN_DATE,
    end_time=_MIN_DATE,
    irradiance=0.0,
    temperature=0.0,
    power=0.0,
    weather=WeatherCode.UNKNOWN
)
_DISCONNECTED: JSONDict = {'connection': 'disconnected'}
_NO_SOLAR_FORECAST = DailySolarForecast([])
_NO_REGISTERS: RegisterBank = EMPTY_REGISTER_BANK

type PossibleDemandWindow = tuple[datetime, datetime] | None


@dataclass(frozen=True)
class _DateKey:
    """
    Immutable calendar date used as a key for daily forecast caches.
    """
    year: int
    month: int
    day: int

    def __str__(self) -> str:
        return f'{self.year:04d}-{self.month:02d}-{self.day:02d}'


@dataclass
class _PrevControl:
    """
    Used to keep track of the previous control state, so the control loop only
    makes changes when needed.
    """
    controller: PowerController | None = None
    control_mode: ControlMode = field(default_factory=ControlMode)
    battery_commanded_mode: BatteryMode = BatteryMode.UNKNOWN
    inverter_commanded_mode: InverterMode = InverterMode.UNKNOWN

    def reset(self, controller: PowerController | None) -> None:
        """
        Reset tracked modes and policies when the controller changes.

        Args:
            controller: Controller associated with the new tracking state.
        """
        self.controller = controller
        self.battery_commanded_mode = BatteryMode.UNKNOWN
        self.inverter_commanded_mode = InverterMode.UNKNOWN
        self.control_mode.battery_mode = BatteryMode.UNKNOWN
        self.control_mode.inverter_mode = InverterMode.UNKNOWN
        self.control_mode.battery_policy = BatteryPolicy.MANUAL
        self.control_mode.inverter_policy = InverterPolicy.MANUAL


class _PriceCache(LifecycleCache[Price]):

    def __init__(self) -> None:
        super().__init__(
            _get_price_now,
            log_error=log_error,
            log_info=log_info,
            old=Constants.PRICE_OLD.total_seconds(),
            retry=Constants.PRICE_SETTLE_CHECK.total_seconds(),
            default=_NO_PRICE,
        )


class _PriceForecastCache(LifecycleCache[Sequence[Price]]):

    def __init__(self) -> None:
        super().__init__(
            _get_price_forecast,
            log_error=log_error,
            log_info=log_info,
            young=Constants.PRICE_FORECAST_YOUNG.total_seconds(),
            old=Constants.PRICE_FORECAST_OLD.total_seconds(),
            default=(),
        )


class _DemandWindowCache(LifecycleCache[PossibleDemandWindow]):

    def __init__(self, day: date):
        super().__init__(
            partial(_get_demand_window, day),
            log_error=log_error,
            log_info=log_info,
            young=Constants.PRICE_DEMAND_WINDOW_YOUNG.total_seconds(),
            old=Constants.PRICE_DEMAND_WINDOW_OLD.total_seconds(),
            default=None,
        )


class _SolarForecastCache(LifecycleCache[DailySolarForecast]):

    def __init__(self, day: date):
        super().__init__(
            partial(_get_solar_forecast, day),
            log_error=log_error,
            log_info=log_info,
            young=Constants.SOLAR_FORECAST_YOUNG.total_seconds(),
            old=Constants.SOLAR_FORECAST_OLD.total_seconds(),
            default=_NO_SOLAR_FORECAST,
        )


# Lock acquisition order: connections -> control -> cache.
@dataclass
class _ConnectionsState:
    """
    Group connection state under the connections lock.

    Connection delegates, settings, and reporting information share one owner.
    """
    lock: OrderedAsyncRLock = field(default_factory=lambda: OrderedAsyncRLock(10))

    # These are the work delegates for accessing the solar power system and database.
    controller: PowerController | None = None
    pricer: PowerPricer | None = None
    forecaster: SolarForecaster | None = None
    consumers: dict[str, PowerConsumer] = field(default_factory=dict)
    database_connections: SolalaDatabaseConnections | None = None

    # Keep track of the settings used to connect to the solar power system.
    controller_settings: ControllerConnection | None = None
    pricer_settings: PricerConnection | None = None
    forecaster_settings: ForecasterConnection | None = None
    consumers_settings: dict[str, ConsumerConnection] = field(default_factory=dict)
    database_settings: DatabaseConnection | None = None

    registers: RegisterBank = field(default_factory=lambda: RegisterBank(()))

    @property
    def controller_connection_info(self) -> JSONDict:
        if self.controller is None:
            return _DISCONNECTED
        else:
            return self.controller.get_connection_info()

    @property
    def pricer_connection_info(self) -> JSONDict:
        if self.pricer is None:
            return _DISCONNECTED
        else:
            return self.pricer.get_connection_info()

    @property
    def forecaster_connection_info(self) -> JSONDict:
        if self.forecaster is None:
            return _DISCONNECTED
        else:
            return self.forecaster.get_connection_info()

    @property
    def consumers_connection_info(self) -> dict[str, JSONDict]:
        return {
            name: consumer.get_connection_info()
            for name, consumer in self.consumers.items()
        }

    @property
    def database_connection_info(self) -> JSONDict:
        if self.database_connections is None:
            return _DISCONNECTED
        else:
            return self.database_connections.get_connection_info()


@dataclass
class _ControlSettingsState:
    """
    Group control settings under the control lock.

    Own desired control modes and previous applied control state.
    """
    lock: OrderedAsyncRLock = field(default_factory=lambda: OrderedAsyncRLock(20))

    control_mode: ControlMode = field(default_factory=ControlMode)
    prev_state: _PrevControl = field(default_factory=_PrevControl)


@dataclass
class _CacheState:
    """
    Group cached readings under the cache lock.

    Own cached power readings and price, demand, and solar forecasts.
    """
    lock: OrderedAsyncRLock = field(default_factory=lambda: OrderedAsyncRLock(30))

    # Caches of status components.
    last_power: PowerStatus = field(default_factory=lambda: _NO_POWER)
    last_power_valid: bool = False
    price_cache: _PriceCache = field(default_factory=_PriceCache)
    demand_window_cache: dict[_DateKey, _DemandWindowCache] = field(default_factory=dict)
    price_forecast_cache: _PriceForecastCache = field(default_factory=_PriceForecastCache)
    solar_forecast_cache: dict[_DateKey, _SolarForecastCache] = field(default_factory=dict)


@dataclass
class _SettingsPersistenceState:
    """
    Hold the settings file path and serialize settings persistence.

    Lock order: connections (10) -> persistence (15) -> control (20) -> cache (30).
    """
    lock: OrderedAsyncRLock = field(default_factory=lambda: OrderedAsyncRLock(15))
    path: Path | None = None


@dataclass
class _ControlState:
    """
    Hold delegate connections, cached readings, control settings, and loop state.

    Mutable connection, control, and cache fields use their dedicated locks.
    """
    connections: _ConnectionsState = field(default_factory=_ConnectionsState)
    database_lifecycle_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    control: _ControlSettingsState = field(default_factory=_ControlSettingsState)
    cache: _CacheState = field(default_factory=_CacheState)
    settings_persistence: _SettingsPersistenceState = field(default_factory=_SettingsPersistenceState)
    health: ControlHealth = field(default_factory=ControlHealth)

    # Listener lists are used on the same asyncio event loop; synchronous updates and snapshots need no lock.
    # Internal control loop tracking variables.
    control_loop_running: bool = True
    control_changed: asyncio.Event = field(default_factory=asyncio.Event)
    control_loop_listeners: list[LoopListener] = field(default_factory=list)
    database_loop_listeners: list[LoopListener] = field(default_factory=list)
    database_write: bool = True
    iteration_start: datetime = field(default_factory=now)  # used to confirm the control loop is running
    registers_to_log: re.Pattern[str] | None = None
    registers_to_log_str: str | None = None

    async def reset_controller(self, controller: PowerController | None, settings: ControllerConnection | None) -> None:
        assert (controller is None) == (settings is None)
        self.connections.controller = controller
        self.connections.controller_settings = settings

        # Replacement hardware has unknown modes; previous policies no longer apply.
        async with _control_settings_state():
            self.control.control_mode.battery_mode = BatteryMode.UNKNOWN
            self.control.control_mode.inverter_mode = InverterMode.UNKNOWN
            self.control.control_mode.battery_policy = BatteryPolicy.MANUAL
            self.control.control_mode.inverter_policy = InverterPolicy.MANUAL

        # Invalidate cached status
        async with _cache_state():
            self.cache.last_power = _NO_POWER
            self.cache.last_power_valid = False

    async def reset_pricer(self, pricer: PowerPricer | None, settings: PricerConnection | None) -> None:
        assert (pricer is None) == (settings is None)
        self.connections.pricer = pricer
        self.connections.pricer_settings = settings

        # Invalidate cached status
        await self.cache.price_cache.invalidate()
        await self.cache.price_forecast_cache.invalidate()
        async with _cache_state():
            self.cache.demand_window_cache.clear()

    async def reset_forecaster(self, forecaster: SolarForecaster | None, settings: ForecasterConnection | None) -> None:
        assert (forecaster is None) == (settings is None)
        self.connections.forecaster = forecaster
        self.connections.forecaster_settings = settings

        # Invalidate cached status
        async with _cache_state():
            self.cache.solar_forecast_cache.clear()

    def reset_consumer(self, consumer_name: str, consumer: PowerConsumer | None,
                       settings: ConsumerConnection | None) -> None:
        if consumer is None:
            assert settings is None
            self.connections.consumers.pop(consumer_name, None)
            self.connections.consumers_settings.pop(consumer_name, None)
            self.health.report_success(f'consumer_status:{consumer_name}')
        else:
            assert settings is not None
            self.connections.consumers[consumer_name] = consumer
            self.connections.consumers_settings[consumer_name] = settings

    def reset_database(self, database: SolalaDatabaseConnections | None,
                       settings: DatabaseConnection | None) -> None:
        assert (database is None) == (settings is None)
        self.connections.database_connections = database
        self.connections.database_settings = settings


_LOG_SRC = '[control loop] '  # prefix for log messages


def get_control_health() -> tuple[Severity, tuple[HealthIssue, ...]]:
    """
    Return a snapshot of overall control health and active issues.

    Returns:
        Current highest severity and immutable issue snapshots.
    """
    health = _CONTROL_STATE.health
    return health.severity, health.get_issues()


def log_debug(message: str) -> None:
    LOGGER.debug(f'{_LOG_SRC}{message}')


def log_info(message: str) -> None:
    LOGGER.info(f'{_LOG_SRC}{message}')


def log_warn(message: str) -> None:
    LOGGER.warn(f'{_LOG_SRC}{message}')


def log_error(message: str) -> None:
    LOGGER.error(f'{_LOG_SRC}{message}')


def log_exception(message: str) -> None:
    """
    Should only be used when handling an exception.
    """
    LOGGER.exception(f'{_LOG_SRC}{message}')


@asynccontextmanager
async def _connections_state() -> AsyncIterator[_ConnectionsState]:
    """
    Get exclusive access to the connection state.
    """
    async with _CONTROL_STATE.connections.lock:
        yield _CONTROL_STATE.connections


@asynccontextmanager
async def _control_settings_state() -> AsyncIterator[_ControlSettingsState]:
    """
    Get exclusive access to the control settings state.
    """
    async with _CONTROL_STATE.control.lock:
        yield _CONTROL_STATE.control


@asynccontextmanager
async def _cache_state() -> AsyncIterator[_CacheState]:
    """
    Get exclusive access to the cache state.
    """
    async with _CONTROL_STATE.cache.lock:
        yield _CONTROL_STATE.cache


# ============================================================================
#  Public control loop functions
# ============================================================================


async def control_loop(
        settings_path: Path | str | None = None,
        settings: Settings | None = None,
        force_settings: bool = False,
        database_write: bool = True,
) -> None:
    """
    Execute the control loop.

    Public asynchronous functions are provided to manage the behaviour of the control loop.
    They must be called from the control loop's asyncio event loop.

    Call `exit_control_loop()` to gracefully terminate the control loop.

    Args:
        settings_path: Path to the settings file, if settings are to be persisted. If provided, the control
            loop will attempt to load settings from the file.

        settings: Settings object to use if the settings file cannot be loaded.

        force_settings: If True, the given settings object will always override any settings loaded from the file.
            Note that if settings are provided, they will override any settings loaded from the file. This includes
            modes and policies if the power controller is reloaded.

        database_write: If False, the control loop will not write to the database. This is useful for testing.
    """

    # Prepare to run the control loop.
    _CONTROL_STATE.control_loop_running = True
    _CONTROL_STATE.database_write = database_write

    # Configure from user settings
    loaded: bool = False
    if settings_path is not None:
        _CONTROL_STATE.settings_persistence.path = Path(settings_path)
        if not force_settings or settings is None:
            loaded = await _load_settings()
    if (not loaded or force_settings) and settings is not None:
        await configure_from_settings(settings)

    database_task = asyncio.create_task(_database_loop())
    try:
        await _control_loop()
    finally:
        database_task.cancel()
        try:
            await database_task
        except asyncio.CancelledError:
            # Expected when shutting down the database loop.
            pass


# =============================================================================
#  Control loop interaction
# =============================================================================


def loop_check_overdue() -> float:
    """
    The control loop is expected to iterate each `Constants.LOOP_TIME` seconds.
    This returns the number of seconds past the last expected loop, i.e.
    `max(0, now - (iteration_start + Constants.LOOP_TIME))`.

    Returns:
        The number of seconds the loop check is overdue (a small number if running normally).
    """
    # We are not concerned with race conditions, so we do not need to get the control loop lock.
    return max(
        0,
        now().timestamp() - (_CONTROL_STATE.iteration_start.timestamp() + Constants.LOOP_TIME.total_seconds())
    )


def exit_control_loop() -> None:
    """
    Flag to exit the control loop on the next iteration.
    """
    # We are not concerned with race conditions, so we do not need to get a lock.
    _CONTROL_STATE.control_loop_running = False
    _CONTROL_STATE.control_changed.set()


async def configure_from_settings(settings: Settings) -> None:
    """
    Configure connections, control modes, policies, etc. as per `settings`.
    """

    # Configure power controller connection
    if settings.controller is not None:
        await connect_controller(settings.controller)

    # Configure power pricer connection
    if settings.pricer is not None:
        await connect_pricer(settings.pricer)

    # Configure named power consumer connections
    if settings.consumers is not None:
        name: str
        consumer_connection: ConsumerConnection
        for name, consumer_connection in settings.consumers.items():
            await connect_consumer(name, consumer_connection)

    if settings.forecaster is not None:
        await connect_forecaster(settings.forecaster)

    if settings.database is not None:
        await connect_database(settings.database)

    if settings.registers_to_log is not None:
        await log_registers(settings.registers_to_log)

    # Initialise control modes
    await set_control(
        battery_mode=settings.battery_mode,
        inverter_mode=settings.inverter_mode,
        battery_policy=settings.battery_policy,
        inverter_policy=settings.inverter_policy,
        disable_export_price_threshold=settings.disable_export_price_threshold,
        enable_export_price_threshold=settings.enable_export_price_threshold,
        start_charge_price_threshold=settings.start_charge_price_threshold,
        stop_charge_price_threshold=settings.stop_charge_price_threshold,
    )


async def get_settings() -> Settings:
    """
    Get a snapshot of the current connection and control settings.

    Returns:
        The current settings.
    """
    async with _connections_state():
        async with _control_settings_state():
            return _get_settings(_CONTROL_STATE)


async def add_control_loop_listener(listener: LoopListener) -> None:
    """
    Register a listener for control loop iterations, moving an existing listener to the end.
    Registering the same listener multiple times causes no problems.

    Args:
    listener: Listener to be updated each control loop iteration.
    """
    try:
        _CONTROL_STATE.control_loop_listeners.remove(listener)
    except ValueError:
        pass
    _CONTROL_STATE.control_loop_listeners.append(listener)


async def remove_control_loop_listener(listener: LoopListener) -> None:
    """
    Unregister a control loop listener, if present.
    No error is raised if the listener is not registered.

    Args:
    listener: Listener to unregister.
    """
    try:
        _CONTROL_STATE.control_loop_listeners.remove(listener)
    except ValueError:
        pass


async def add_database_loop_listener(listener: LoopListener) -> None:
    """
    Register a listener for database loop iterations.
    Registering the same listener multiple times causes no problems.

    Args:
    listener: Listener to be updated each database loop iteration.
    """
    try:
        _CONTROL_STATE.database_loop_listeners.remove(listener)
    except ValueError:
        pass
    _CONTROL_STATE.database_loop_listeners.append(listener)


async def remove_database_loop_listener(listener: LoopListener) -> None:
    """
    Unregister a database loop listener, if present.
    No error is raised if the listener is not registered.

    Args:
    listener: Listener to unregister.
    """
    try:
        _CONTROL_STATE.database_loop_listeners.remove(listener)
    except ValueError:
        pass


async def get_control_mode() -> ControlMode:
    """
    Get what the control loop is aiming to do for the user.
    """
    async with _control_settings_state() as state:
        return state.control_mode.copy()


async def get_prev_control_mode() -> ControlMode:
    """
    Get the control mode last requested by the control loop.

    This is not a verified hardware state. Inverter DISABLE and ZERO_EXPORT
    commands are retried every iteration, even when a command fails.
    """
    async with _control_settings_state() as state:
        return state.prev_state.control_mode.copy()


async def get_power_status() -> PowerStatus:
    """
    Get the power status.
    If a valid cached power status exists, it is returned.
    Otherwise, the status is obtained from the power controller and cached.

    Returns:
        The current cached status, or the default status if no controller is connected.
    """
    async with _connections_state() as connections:
        async with _cache_state() as cache:
            if cache.last_power_valid:
                return cache.last_power

            controller: PowerController | None = connections.controller
            if controller is None:
                cache.last_power = _NO_POWER
                if _CONTROL_STATE.health.report_failure(
                        'power_status', Severity.CAUTION, 'Power status unavailable: controller disconnected'):
                    log_error('Power update not available. Error: power controller not connected')
            else:
                try:
                    status = await controller.get_status()
                except Exception:
                    cache.last_power = _NO_POWER
                    if _CONTROL_STATE.health.report_failure(
                            'power_status', Severity.CAUTION, 'Power status could not be read'):
                        log_exception('Power status update failed')
                else:
                    cache.last_power = status
                    cache.last_power_valid = True
                    if _CONTROL_STATE.health.report_success('power_status'):
                        log_info('Power status recovered after previous failure')
            return cache.last_power


def get_register_bank() -> RegisterBank:
    """
    Return the current immutable mapping of named registers.

    Register values are obtained separately and may change or become
    unavailable after the bank is returned.
    """
    return _CONTROL_STATE.connections.registers


async def get_price_now() -> Price:
    """
    Get the current price from the power pricer.
    """
    return await _CONTROL_STATE.cache.price_cache()  # defers to _get_price_now()


async def _get_price_now() -> LifecycleReturn[Price]:
    pricer = _CONTROL_STATE.connections.pricer
    if pricer is None:
        return error('Price update not available. Error: power pricer not connected')

    try:
        price: Price = await pricer.get_price()
    except Exception as err:
        return error(f'Price update not available. {err!r}')

    if pricer is not _CONTROL_STATE.connections.pricer:
        # The pricer got changed, abandon the update
        # The issue will be corrected naturally when next polled.
        return error('Price update not available. Error: power pricer changed')

    note = ' (estimate)' if price.is_estimate else ''
    log_info(f'Updated current price: {price.buy_price} {price.feed_in_price} {note}')

    if price.is_estimate:
        return interim(price, expires_at=price.end_time)
    else:
        return valid(price, refresh_at=price.end_time, expires_at=price.end_time)


async def get_price_now_no_estimate(max_tries: int = 10) -> Price:
    """
    Get the current price from the power pricer, looping until the price is not an estimate.

    The returned price may be an estimate if the pricer is not available or could not
    provide a non-estimate price within the given number of tries.

    Args:
        max_tries: the maximum number of attempts should the pricer return a price estimate.

    Returns:
        A price for the current time. The returned price may still be an estimate if
        `max_tries` was exhausted.
    """
    price: Price = await get_price_now()
    max_tries -= 1
    while price.is_estimate and max_tries > 1 and _CONTROL_STATE.connections.pricer is not None:
        max_tries -= 1
        await asyncio.sleep(Constants.PRICE_SETTLE_CHECK.total_seconds())
        price = await get_price_now()
    return price


async def get_demand_window(day: date) -> PossibleDemandWindow:
    """
    Get the demand window for the given day.

    Returns None if the demand window is not active on the given day.
    """
    async with _cache_state() as cache:
        key = _DateKey(day.year, day.month, day.day)
        demand_window_cache: _DemandWindowCache | None = cache.demand_window_cache.get(key)
        if demand_window_cache is None:
            demand_window_cache: _DemandWindowCache = _DemandWindowCache(day)
            cache.demand_window_cache[key] = demand_window_cache
        demand_window_cache: _DemandWindowCache
    return await demand_window_cache()  # defers to _get_demand_window


async def _get_demand_window(day: date) -> LifecycleReturn[PossibleDemandWindow]:
    pricer = _CONTROL_STATE.connections.pricer
    if pricer is None:
        return error('Demand window not available. Error: power pricer not connected')

    try:
        demand_window = await pricer.get_demand_window(day)
    except Exception as err:
        return error(f'Demand window not available. Error: {err!r}')

    if pricer is not _CONTROL_STATE.connections.pricer:
        # The pricer got changed, abandon the update
        # The issue will be corrected naturally when next polled.
        return error('Demand window not available. Error: power pricer changed')

    log_info(f'Updated price demand window: day = {day.strftime("%Y-%m-%d")}')
    return valid(demand_window)


async def get_price_forecast() -> Sequence[Price]:
    """
    Get the forecast prices from the power pricer.

    Get the 30-minute price forecasts, in ascending order of time from now.
    Nominally this will return `Constants.PRICE_FORECAST_DURATION * 2` prices
    but may be less (or zero) if there is an error.

    Errors will be logged but should not raise an exception.
    """
    prices: Sequence[Price] = await _CONTROL_STATE.cache.price_forecast_cache()  # defers to _get_price_forecast()

    # A race condition or error may mean that the first forecast is already in the past.
    while len(prices) > 0 and prices[0].end_time < now():
        log_info(f'Price forecast contains old data: {prices[0]}')
        prices = prices[1:]

    return prices[:_needed_forecasts()]


def _needed_forecasts() -> int:
    """
    How many 30-minute forecasts are needed to cover.
    """
    return int(math.ceil(Constants.PRICE_FORECAST_DURATION.total_seconds() / 60 / 30))


async def _get_price_forecast() -> LifecycleReturn[Sequence[Price]]:
    pricer = _CONTROL_STATE.connections.pricer
    if pricer is None:
        return error('Price forecast not available. Error: power pricer not connected')

    try:
        # Plus one to account for possible race condition
        prices: list[Price] = await pricer.get_price_forecast(_needed_forecasts() + 1)
        log_info('Price forecast updated')
    except Exception as err:
        return error(f'Price forecast not available. Error: {err!r}')

    if pricer is not _CONTROL_STATE.connections.pricer:
        # The pricer got changed, abandon the update
        # The issue will be corrected naturally when next polled.
        return error('Price forecast not available. Error: power pricer changed')

    if len(prices) == 0:
        return error('Price forecast not available. Error: power pricer returned no prices')

    log_info('Updated price forecast')
    return valid(prices, refresh_at=prices[0].end_time)


async def get_consumers_status() -> dict[str, ConsumerStatus]:
    """
    Get the status of each registered power consumer.

    Returns:
        A mapping from each consumer name to its status.
    """
    async with _connections_state() as connections:
        # Keep consumers connected until all status requests complete.
        consumers = tuple(connections.consumers.items())
        statuses = await asyncio.gather(
            *(consumer.get_status() for _, consumer in consumers),
            return_exceptions=True,
        )

    result: dict[str, ConsumerStatus] = {}
    for (name, _), status in zip(consumers, statuses):
        if isinstance(status, BaseException):
            if isinstance(status, asyncio.CancelledError):
                raise status
            if _CONTROL_STATE.health.report_failure(
                    f'consumer_status:{name}', Severity.CAUTION,
                    f'Consumer {name!r} status unavailable'):
                log_error(f'Consumer {name!r} status unavailable: {status!r}')
        else:
            if _CONTROL_STATE.health.report_success(f'consumer_status:{name}'):
                log_info(f'Consumer {name!r} status recovered')
            result[name] = status
    return result


async def get_connection_info() -> JSONDict:
    """
    Get connection information for the configured system delegates and the database.

    Returns:
        A JSON-compatible dictionary of connection information.
    """
    async with _connections_state() as connections:
        result: dict[str, JSONValue] = {
            'controller': connections.controller_connection_info,
            'pricer': connections.pricer_connection_info,
            'forecaster': connections.forecaster_connection_info,
            'database': connections.database_connection_info,
        }
        if len(connections.consumers) > 0:
            result['consumers'] = connections.consumers_connection_info
        return result


async def get_status() -> JSONDict:
    """
    Take a snapshot of the current overall status, as a JSON dictionary.
    """
    control_mode: ControlMode
    power_status: PowerStatus
    price: Price
    consumers_status: dict[str, ConsumerStatus]

    control_mode, power_status, price, consumers_status = await asyncio.gather(
        get_control_mode(),
        get_power_status(),
        get_price_now(),
        get_consumers_status(),
    )

    power_json: JSONDict = power_status.to_json()
    if len(consumers_status) > 0:
        power_json: dict[str, JSONValue] = dict(power_json)
        power_json['consumers'] = {
            consumer: status.to_json()
            for consumer, status in consumers_status.items()
        }
        total = sum(json_num(consumer.power) for consumer in consumers_status.values())
        house_power = power_status.house_power
        power_json['consumers_total'] = total
        power_json['consumers_remaining'] = house_power - total

    return {
        'control': control_mode.to_json(),
        'power': power_json,
        'price': price.to_json(datetime_format=GUI_TIMESTAMP_FORMAT, include_time=False),
    }


async def get_solar_forecast(day: date) -> DailySolarForecast:
    """
    Get the daily forecast for solar power, for the given date.
    """
    async with _cache_state() as cache:
        key = _DateKey(day.year, day.month, day.day)
        solar_forecast_cache: _SolarForecastCache | None = cache.solar_forecast_cache.get(key)
        if solar_forecast_cache is None:
            solar_forecast_cache: _SolarForecastCache = _SolarForecastCache(day)
            cache.solar_forecast_cache[key] = solar_forecast_cache
        solar_forecast_cache: _SolarForecastCache
    return await solar_forecast_cache()  # defers to _get_solar_forecast


async def _get_solar_forecast(day: date) -> LifecycleReturn[DailySolarForecast]:
    forecaster = _CONTROL_STATE.connections.forecaster
    if forecaster is None:
        return error(f'Solar forecast not available for {day.strftime("%Y-%m-%d")}. Error: solar forecaster not connected')

    try:
        forecast: DailySolarForecast = await forecaster.get_forecast(day)
    except Exception as err:
        return error(f'Solar forecast not available for {day.strftime("%Y-%m-%d")}. Error: {err!r}')

    if forecaster is not _CONTROL_STATE.connections.forecaster:
        # The forecaster got changed, abandon the update.
        # The issue will be corrected naturally when next polled.
        return error(f'Solar forecast not available for {day.strftime("%Y-%m-%d")}. Error: solar forecaster changed')

    log_info(f'Updated solar forecast for day {day.strftime("%Y-%m-%d")}')
    return valid(forecast)


@asynccontextmanager
async def _database() -> AsyncIterator[SolalaDatabase]:
    """
    Reserve the current database pool before releasing the connections lock.

    The reservation is released only after the database context has returned
    its connection, including when acquisition fails or is cancelled.
    """
    reservation = None
    try:
        async with _connections_state() as connections:
            pool = connections.database_connections
            if pool is None:
                raise ConnectionError('Database pool not connected')
            reservation = pool.reserve_database()

        async with reservation as db:
            yield db
    finally:
        if reservation is not None:
            reservation.release()


async def solala_database_measurements(day: date) -> Sequence[Measurement]:
    """
    Read measurements for a day from the application database.

    Return an empty sequence if no measurements are available or if database
    access fails with a connection or database error.

    Args:
        day: Local date for which to retrieve measurements.

    Returns:
        Measurements for the day, or an empty sequence if database access fails.
    """
    try:
        async with _database() as db:
            return await db.get_measurements(day)
    except (ConnectionError, DatabaseError) as err:
        log_error(f'Database connection error: {err!r}')
        return []


async def set_control(
        *,
        battery_mode: BatteryMode | None = None,
        inverter_mode: InverterMode | None = None,
        battery_policy: BatteryPolicy | None = None,
        inverter_policy: InverterPolicy | None = None,
        # NEG_FEED_IN_ZERO_EXPORT parameters
        disable_export_price_threshold: float | None = None,
        enable_export_price_threshold: float | None = None,
        # CHEAP_CHARGE parameters
        start_charge_price_threshold: float | None = None,
        stop_charge_price_threshold: float | None = None,
) -> None:
    """
    Set the control loop modes, policies, and policy parameters.

    Parameters left as None retain their current values.
    Export and charge thresholds must each be strictly ordered to provide hysteresis.

    Args:
        battery_mode: Requested battery operating mode.
        inverter_mode: Requested inverter operating mode.
        battery_policy: Policy controlling automatic battery mode selection.
        inverter_policy: Policy controlling automatic inverter mode selection.
        disable_export_price_threshold: Feed-in price below which export is disabled.
        enable_export_price_threshold: Feed-in price above which export is enabled.
        start_charge_price_threshold: Buy price below which forced charging starts.
        stop_charge_price_threshold: Buy price above which forced charging stops.

    Raises:
        ControlLoopError: If either pair of price thresholds is not strictly ordered.
    """
    async with _connections_state():
        async with _control_settings_state() as state:
            control_mode = state.control_mode

            if disable_export_price_threshold is None:
                disable_export_price_threshold = control_mode.disable_export_price_threshold
            if enable_export_price_threshold is None:
                enable_export_price_threshold = control_mode.enable_export_price_threshold
            if start_charge_price_threshold is None:
                start_charge_price_threshold = control_mode.start_charge_price_threshold
            if stop_charge_price_threshold is None:
                stop_charge_price_threshold = control_mode.stop_charge_price_threshold

            if disable_export_price_threshold >= enable_export_price_threshold:
                raise ControlLoopError('export price threshold: disable must be less than enable')
            if start_charge_price_threshold >= stop_charge_price_threshold:
                raise ControlLoopError('charge price threshold: start must be less than stop')

            if battery_mode is not None:
                control_mode.battery_mode = battery_mode
            if inverter_mode is not None:
                control_mode.inverter_mode = inverter_mode
            if battery_policy is not None:
                control_mode.battery_policy = battery_policy
            if inverter_policy is not None:
                control_mode.inverter_policy = inverter_policy

            control_mode.disable_export_price_threshold = disable_export_price_threshold
            control_mode.enable_export_price_threshold = enable_export_price_threshold
            control_mode.start_charge_price_threshold = start_charge_price_threshold
            control_mode.stop_charge_price_threshold = stop_charge_price_threshold

            control_json = control_mode.to_json()

        # Wake the loop promptly; the next step will copy the settings.
        _CONTROL_STATE.control_changed.set()

        # Saving takes the connections lock before the control-settings lock.
        # Do not call it while already holding the latter.
        await _save_settings()
        log_info(f'Control: {json.dumps(control_json)}')


async def log_registers(match: str | re.Pattern[str] | None) -> None:
    """
    Select registers to log to the database.

    Args:
        match: Regular expression matching register names, or None to disable logging.
            Use `MATCH_ALL` to match all registers.
    """
    if match is None:
        _CONTROL_STATE.registers_to_log = None
        _CONTROL_STATE.registers_to_log_str = None
    elif isinstance(match, re.Pattern):
        _CONTROL_STATE.registers_to_log = match
        _CONTROL_STATE.registers_to_log_str = match.pattern
    else:
        _CONTROL_STATE.registers_to_log = re.compile(match)
        _CONTROL_STATE.registers_to_log_str = match


# =============================================================================
#  Connection management for power control and price
# =============================================================================

async def connect_controller(controller_connection: ControllerConnection) -> None:
    """
    Connect or replace the power controller using the given settings.

    Args:
        controller_connection: Power controller connection configuration.
    """
    async with _connections_state():
        controller: PowerController

        if controller_connection.type == DummyControllerConnection.TYPE:
            assert isinstance(controller_connection, DummyControllerConnection)
            controller = _connect_dummy_controller(controller_connection)
        elif controller_connection.type == ModbusControllerConnection.TYPE:
            assert isinstance(controller_connection, ModbusControllerConnection)
            controller = _connect_modbus(controller_connection)
        else:
            raise ControlLoopError(
                'unknown controller connection type',
                errors={'type': controller_connection.type}
            )

        await disconnect_controller()
        await _CONTROL_STATE.reset_controller(controller, controller_connection)
        connection_info = controller.get_connection_info()
        log_info(f'Power controller connection: {json.dumps(connection_info)}')
        await _save_settings()
        await _reconfigure_registers(_CONTROL_STATE)


async def disconnect_controller() -> None:
    """
    Close the power controller connection.
    """
    async with _connections_state():
        if _CONTROL_STATE.connections.controller is not None:
            await _CONTROL_STATE.connections.controller.close()
            await _CONTROL_STATE.reset_controller(None, None)
            log_info('Power controller disconnected')
        await _save_settings()
        await _reconfigure_registers(_CONTROL_STATE)


async def connect_pricer(pricer_connection: PricerConnection) -> None:
    """
    Connect or replace the power pricer using the given settings.

    Args:
        pricer_connection: Power pricer connection configuration.
    """
    async with _connections_state():
        pricer: PowerPricer

        if pricer_connection.type == DummyPricerConnection.TYPE:
            assert isinstance(pricer_connection, DummyPricerConnection)
            pricer = _connect_dummy_pricer(pricer_connection)
        elif pricer_connection.type == AmberPricerConnection.TYPE:
            assert isinstance(pricer_connection, AmberPricerConnection)
            pricer = _connect_amber(pricer_connection)

        else:
            raise ControlLoopError('unknown pricer connection type', errors={'type': pricer_connection.type})

        await disconnect_pricer()
        await _CONTROL_STATE.reset_pricer(pricer, pricer_connection)
        connection_info = pricer.get_connection_info()
        log_info(f'Power pricer connection: {json.dumps(connection_info)}')
        await _save_settings()
        await _reconfigure_registers(_CONTROL_STATE)


async def disconnect_pricer() -> None:
    """
    Close the power pricer connection.
    """
    async with _connections_state():
        if _CONTROL_STATE.connections.pricer is not None:
            await _CONTROL_STATE.connections.pricer.close()
            await _CONTROL_STATE.reset_pricer(None, None)
            log_info('Pricer disconnected')
        await _save_settings()
        await _reconfigure_registers(_CONTROL_STATE)


async def connect_consumer(name: str, consumer_connection: ConsumerConnection) -> None:
    """
    Connect or replace a named power consumer.

    Args:
        name: Name identifying the consumer.
        consumer_connection: Power consumer connection configuration.
    """
    async with _connections_state():
        consumer: PowerConsumer

        if consumer_connection.type == DummyConsumerConnection.TYPE:
            assert isinstance(consumer_connection, DummyConsumerConnection)
            consumer = _connect_dummy_consumer(consumer_connection)
        elif consumer_connection.type == TeslaWallConnectorConnection.TYPE:
            assert isinstance(consumer_connection, TeslaWallConnectorConnection)
            consumer = _connect_tesla_wall_connector(consumer_connection)
        elif consumer_connection.type == TuyaConnection.TYPE:
            assert isinstance(consumer_connection, TuyaConnection)
            consumer = _connect_tuya(consumer_connection)
        else:
            raise ControlLoopError(
                'unknown consumer connection type',
                errors={'name': name, 'type': consumer_connection.type}
            )

        await disconnect_consumer(name)
        _CONTROL_STATE.reset_consumer(name, consumer, consumer_connection)
        connection_info = consumer.get_connection_info()
        log_info(f'Power consumer {name!r} connection: {json.dumps(connection_info)}')
        await _save_settings()
        await _reconfigure_registers(_CONTROL_STATE)


async def disconnect_consumer(name: str) -> None:
    """
    Close a power consumer connection.
    """
    async with _connections_state():
        consumer: PowerConsumer | None = _CONTROL_STATE.connections.consumers.get(name)
        if consumer is not None:
            await consumer.close()
            _CONTROL_STATE.reset_consumer(name, None, None)
            log_info('Power consumer {name!r} disconnected')
        await _save_settings()
        await _reconfigure_registers(_CONTROL_STATE)


async def connect_forecaster(forecaster_connection: ForecasterConnection) -> None:
    """
    Connect or replace the solar forecaster using the given settings.

    Args:
        forecaster_connection: Solar forecaster connection configuration.
    """
    async with _connections_state():
        forecaster: SolarForecaster

        if forecaster_connection.type == DummySolarForecasterConnection.TYPE:
            assert isinstance(forecaster_connection, DummySolarForecasterConnection)
            forecaster = _connect_dummy_solar_forecaster(forecaster_connection)
        elif forecaster_connection.type == OpenMeteoConnection.TYPE:
            assert isinstance(forecaster_connection, OpenMeteoConnection)
            forecaster = _connect_open_meteo_forecaster(forecaster_connection)
        else:
            raise ControlLoopError(
                'unknown forecaster connection type',
                errors={'type': forecaster_connection.type}
            )

        await disconnect_forecaster()
        await _CONTROL_STATE.reset_forecaster(forecaster, forecaster_connection)
        connection_info = forecaster.get_connection_info()
        log_info(f'Solar forecaster connection: {json.dumps(connection_info)}')
        await _save_settings()
        await _reconfigure_registers(_CONTROL_STATE)


async def disconnect_forecaster() -> None:
    """
    Close the solar forecaster connection.
    """
    async with _connections_state():
        if _CONTROL_STATE.connections.forecaster is not None:
            await _CONTROL_STATE.connections.forecaster.close()
            await _CONTROL_STATE.reset_forecaster(None, None)
            log_info('Solar forecaster disconnected')
        await _save_settings()
        await _reconfigure_registers(_CONTROL_STATE)


async def _close_database_pool(pool: SolalaDatabaseConnections) -> None:
    """
    Complete pool shutdown even if the calling task is cancelled.

    Cancellation is propagated after the pool has finished closing, so the
    database lifecycle lock remains held throughout the transition.
    """
    closing = asyncio.create_task(pool.close())
    cancelled = False
    # Keep awaiting the shielded close after cancellation. This deliberately
    # delays cancellation propagation until shutdown has completed, so the
    # lifecycle lock cannot be released while the old pool is still closing.
    while not closing.done():
        try:
            await asyncio.shield(closing)
        except asyncio.CancelledError:
            cancelled = True
    # Propagate any failure from the close operation rather than hiding it.
    await closing
    if cancelled:
        raise asyncio.CancelledError


async def connect_database(database_connection: DatabaseConnection) -> None:
    """
    Replace the database pool without holding the connections lock while draining.

    Args:
        database_connection: Database connection configuration.
    """
    async with _CONTROL_STATE.database_lifecycle_lock:
        database_connections = SolalaDatabaseConnections(
            role=database_connection.role,
            password=database_connection.password,
            host=database_connection.host,
            port=database_connection.port,
            database_name=database_connection.database_name,
        )
        async with _connections_state() as connections:
            old_pool = connections.database_connections
            if old_pool is not None:
                old_pool.begin_close()
            _CONTROL_STATE.reset_database(None, None)

        if old_pool is not None:
            await _close_database_pool(old_pool)

        async with _connections_state():
            _CONTROL_STATE.reset_database(database_connections, database_connection)
            connection_info = database_connections.get_connection_info()
            log_info(f'Database connection: {json.dumps(connection_info)}')
            await _save_settings()
            # no need to _reconfigure_registers(state)


async def disconnect_database() -> None:
    """
    Close the database pool without blocking the connections lock during drain.
    """
    async with _CONTROL_STATE.database_lifecycle_lock:
        async with _connections_state() as connections:
            old_pool = connections.database_connections
            if old_pool is not None:
                old_pool.begin_close()
                _CONTROL_STATE.reset_database(None, None)

        if old_pool is not None:
            await _close_database_pool(old_pool)
            log_info('Database disconnected')

        await _save_settings()
        # no need to _reconfigure_registers(state)


# =============================================================================
#  Support functions
# =============================================================================


async def _database_loop() -> None:
    """
    Execute the database logging loop.
    """
    # Note that this loop avoids locking the control state as much as possible
    # to keep out of the way of the control loop.

    log_info('Running database loop')
    while _CONTROL_STATE.control_loop_running:
        iteration_start = now()
        if _CONTROL_STATE.database_write:
            try:
                async with _database() as db:
                    await _insert_measurement(iteration_start, db)
            except Exception:
                # A failed measurement must not stop subsequent logging cycles.
                # Cancellation still propagates to the caller.
                if _CONTROL_STATE.health.report_failure(
                        'database_measurement', Severity.CAUTION,
                        'Database measurement could not be saved'):
                    log_exception('Database measurement failed')
            else:
                if _CONTROL_STATE.health.report_success('database_measurement'):
                    log_info('Database measurements recovered after previous failure')

        listeners = _CONTROL_STATE.database_loop_listeners.copy()
        # Notify listeners without holding a state lock.
        _update_listeners(listeners)

        # Sleep for the remaining time until the next loop iteration.
        iter_time: int = int(Constants.DATABASE_LOG_LOOP_TIME.total_seconds())
        start_timestamp: int = (int(iteration_start.timestamp() / iter_time) + 1) * iter_time
        sleeptime: float = start_timestamp - now().timestamp()
        await asyncio.sleep(max(0.0, sleeptime))

    log_info('Stopped database loop')


async def _insert_measurement(dt_now: datetime, db: SolalaDatabase) -> None:
    """
    Collect current system readings and write a database measurement.

    Args:
        dt_now: Timestamp of the measurement.
        db: Database interface used to store the measurement.
    """
    log_info('Gathering a measurement for the database')
    today = dt_now.astimezone(local_time_zone()).date()

    control_mode: ControlMode
    power_status: PowerStatus
    price: Price
    daily_forecast: DailySolarForecast
    control_mode, power_status, price, daily_forecast = await asyncio.gather(
        get_prev_control_mode(),
        get_power_status(),
        get_price_now_no_estimate(),
        get_solar_forecast(today)
    )

    forecast: SolarForecast | None = daily_forecast.find_contemporary(dt_now)
    if forecast is None:
        log_warn(f'No solar forecast found for {dt_now.strftime("%Y-%m-%d")}')
        forecast: SolarForecast = _NO_FORECAST

    measurement = Measurement(
        timestamp=dt_now,
        solar_power=power_status.solar_power,
        grid_power=power_status.grid_power,
        house_power=power_status.house_power,
        battery_power=power_status.battery_power,
        battery_charge=power_status.state_of_charge,
        buy_price=price.buy_price,
        feed_in_price=price.feed_in_price,
        renewables=price.renewables,
        accumulated_solar_energy=power_status.accumulated_solar_energy,
        accumulated_grid_energy_import=power_status.accumulated_grid_energy_import,
        accumulated_grid_energy_export=power_status.accumulated_grid_energy_export,
        accumulated_battery_energy_charge=power_status.accumulated_battery_energy_charge,
        accumulated_battery_energy_discharge=power_status.accumulated_battery_energy_discharge,
        battery_mode=control_mode.battery_mode,
        battery_policy=control_mode.battery_policy,
        inverter_mode=control_mode.inverter_mode,
        inverter_policy=control_mode.inverter_policy,
        forecast_irradiance=forecast.irradiance,
        forecast_temperature=forecast.temperature,
        forecast_power=forecast.power,
        forecast_weather=forecast.weather,
    )
    await db.insert_measurement(measurement)
    log_info('Inserted a measurement into the database')


async def _control_loop() -> None:
    """
    Execute the main control loop.
    """
    log_info('Running control loop')

    # Sleep to start the loop on a preferred time boundary.
    # Also gives some time to queued async tasks.
    await _wait_for_control_change(_CONTROL_STATE, _get_sleep_time())

    while _CONTROL_STATE.control_loop_running:
        state = _CONTROL_STATE
        state.iteration_start = iteration_start = now()  # timestamp to calculate loop sleep time
        # Hold the connections lock while issuing commands to prevent
        # controller replacement or closure during a control step.
        try:
            async with _connections_state():
                await _control_step(state)
        except Exception:
            # Do not automatically retry an uncertain hardware command here.
            # Continue on the next scheduled iteration instead.
            if state.health.report_failure('control_step', Severity.WARNING,
                                           'Control step failed'):
                log_exception('Control step failed')
        else:
            if state.health.report_success('control_step'):
                log_info('Control step recovered after previous failure')
        # Ancillary work must not prevent the next control iteration.
        try:
            async with _cache_state() as cache:
                cache.last_power_valid = False
        except Exception:
            log_exception('Power cache invalidation failed')

        if state.registers_to_log is not None:
            try:
                await _cur_log_registers(state.registers_to_log)
            except Exception:
                if state.health.report_failure('register_logging', Severity.CAUTION,
                                               'Diagnostic register logging failed'):
                    log_exception('Register logging failed')
            else:
                if state.health.report_success('register_logging'):
                    log_info('Diagnostic register logging recovered after previous failure')

        # Listener callbacks are dispatched without holding state locks.
        _update_listeners(state.control_loop_listeners.copy())

        # Sleep for the remaining time until the next loop iteration.
        sleep_time = _get_sleep_time()
        loop_time_multiple = (
                (now().timestamp() - iteration_start.timestamp() + sleep_time)
                / Constants.LOOP_TIME.total_seconds()
        )
        if loop_time_multiple > 1:
            log_warn(f'Loop time multiple > 1 ({loop_time_multiple})')
        await _wait_for_control_change(state, sleep_time)

    log_info('Stopped control loop')


async def _wait_for_control_change(state: _ControlState, timeout: float) -> None:
    """
    Wait until control settings change or the periodic deadline arrives.

    The event is cleared when the next step snapshots settings, not here,
    so changes during a step cannot be lost.
    """
    try:
        await asyncio.wait_for(state.control_changed.wait(), timeout=timeout)
    except TimeoutError:
        pass


def _get_sleep_time() -> float:
    """
    Return the sleep time required to wake up on a Constants.LOOP_TIME multiple.
    The result is > Constants.LOOP_MIN_SLEEP_TIME.
    """
    ts: float = now().timestamp()
    loop_time: int = int(Constants.LOOP_TIME.total_seconds())
    start_timestamp = int(ts / loop_time + 1) * loop_time
    sleep_time = start_timestamp - ts
    while sleep_time < Constants.LOOP_MIN_SLEEP_TIME.total_seconds():
        start_timestamp += loop_time
        sleep_time = start_timestamp - ts
    return sleep_time


async def _cur_log_registers(cur_log_registers: re.Pattern[str] | None) -> None:
    """
    Log numeric and text values of registers matching the configured pattern.

    Boolean values are stored as 1 or 0 alongside numeric values. String
    values are stored separately as text.

    Args:
        cur_log_registers: Compiled name pattern, or None to skip logging.
    """
    if cur_log_registers is not None:
        timestamp = now()
        registers = await get_register_bank().get_register_values(cur_log_registers)
        to_log_numeric: dict[str, int | float] = {}
        to_log_text: dict[str, str] = {}
        for name, value in registers.items():
            if isinstance(value, bool):
                to_log_numeric[name] = 1 if value else 0
            elif isinstance(value, (int, float)):
                to_log_numeric[name] = value
            elif isinstance(value, str):
                to_log_text[name] = value
        async with _database() as db:
            await db.insert_registers_numeric(timestamp, to_log_numeric)
            await db.insert_registers_text(timestamp, to_log_text)


async def _control_step(state: _ControlState) -> None:
    """
    Perform one functional step while the caller holds the connections lock.

    Each step uses one snapshot of control settings. Changes made during the
    step are handled on a subsequent iteration.
    """
    async with _control_settings_state() as control_state:
        # Acknowledge changes at the start of every step, even without a
        # connected controller. Later changes will signal the next step.
        state.control_changed.clear()
        prev_state = control_state.prev_state
        controller = _check_power_controller(state, prev_state)
        if controller is None:
            return
        requested_mode = control_state.control_mode.copy()
        # Preserve the effective mode within a policy's hysteresis band.
        # A policy change starts from the newly requested mode instead.
        if requested_mode.battery_policy == prev_state.control_mode.battery_policy:
            if requested_mode.battery_policy != BatteryPolicy.MANUAL:
                requested_mode.battery_mode = prev_state.control_mode.battery_mode
        if requested_mode.inverter_policy == prev_state.control_mode.inverter_policy:
            if requested_mode.inverter_policy != InverterPolicy.MANUAL:
                requested_mode.inverter_mode = prev_state.control_mode.inverter_mode
    # Control step operates within locked connections so `pricer` is stable
    pricer_available: bool = state.connections.pricer is not None

    # Do not hold the settings lock across price retrieval or hardware I/O.
    # We operate on the settings `requested_mode` copied above.

    try:
        await _apply_battery_policy(requested_mode, pricer_available)
    except Exception:
        # Preserve the last effective battery mode rather than falling back
        # to the originally requested mode after a failed price lookup.
        requested_mode.battery_mode = prev_state.control_mode.battery_mode
        if state.health.report_failure('battery_policy', Severity.CAUTION,
                                       'Battery price policy could not be evaluated'):
            log_exception('Battery price policy failed')
    else:
        if state.health.report_success('battery_policy'):
            log_info('Battery price policy issue resolved')
    await _execute_battery_mode(state, prev_state, controller, requested_mode)

    try:
        await _apply_inverter_policy(requested_mode, pricer_available)
    except Exception:
        # Preserve the last effective mode so that an active inverter safety
        # command still receives its keep-alive when price retrieval fails.
        requested_mode.inverter_mode = prev_state.control_mode.inverter_mode
        if state.health.report_failure('inverter_policy', Severity.CAUTION,
                                       'Inverter price policy could not be evaluated'):
            log_exception('Inverter price policy failed')
    else:
        if state.health.report_success('inverter_policy'):
            log_info('Inverter price policy issue resolved')
    await _execute_inverter_mode(state, prev_state, controller, requested_mode)

    async with _control_settings_state():
        # Preserve the last request, even if a command failed.
        prev_state.control_mode = requested_mode


def _check_power_controller(state: _ControlState, prev_state: _PrevControl) -> PowerController | None:
    """
    Reset tracking if the power controller is absent or has changed.
    """
    controller = state.connections.controller
    if controller is None:
        prev_state.reset(None)
    elif controller is not prev_state.controller:
        prev_state.reset(controller)
    return controller


async def _apply_battery_policy(control_mode: ControlMode, pricer_available: bool) -> None:
    """
    Apply the battery pricing policy to the requested mode.
    """
    if not pricer_available or control_mode.battery_policy != BatteryPolicy.CHEAP_CHARGE:
        return

    price = await get_price_now()
    if price.buy_price < control_mode.start_charge_price_threshold:
        control_mode.battery_mode = BatteryMode.FORCE_CHARGE
    elif price.buy_price > control_mode.stop_charge_price_threshold:
        control_mode.battery_mode = BatteryMode.ENABLE


async def _apply_inverter_policy(control_mode: ControlMode, pricer_available: bool) -> None:
    """
    Apply the inverter pricing policy to the requested mode.
    """
    if not pricer_available or control_mode.inverter_policy != InverterPolicy.NEG_FEED_IN_ZERO_EXPORT:
        return

    price = await get_price_now()
    if price.feed_in_price < control_mode.disable_export_price_threshold:
        control_mode.inverter_mode = InverterMode.ZERO_EXPORT
    elif price.feed_in_price > control_mode.enable_export_price_threshold:
        control_mode.inverter_mode = InverterMode.ENABLE


async def _execute_battery_mode(
        state: _ControlState,
        prev_state: _PrevControl,
        power_controller: PowerController,
        requested_mode: ControlMode,
) -> None:
    """
    Execute a changed battery command and record its outcome.
    """
    battery_mode_changed: bool = requested_mode.battery_mode != prev_state.control_mode.battery_mode
    if battery_mode_changed:
        try:
            match requested_mode.battery_mode:
                case BatteryMode.ENABLE:
                    await power_controller.enable_battery()
                case BatteryMode.DISABLE:
                    await power_controller.disable_battery()
                case BatteryMode.FORCE_CHARGE:
                    await power_controller.force_charge()
                case BatteryMode.FORCE_DISCHARGE:
                    await power_controller.force_discharge()
                case BatteryMode.CHARGE_ONLY:
                    await power_controller.charge_only()
                case BatteryMode.DISCHARGE_ONLY:
                    await power_controller.discharge_only()
        except Exception:
            # A partial write can leave hardware state unknown. Reconciliation
            # is required before attempting an automatic retry.
            prev_state.battery_commanded_mode = BatteryMode.UNKNOWN
            if state.health.report_failure('battery_command', Severity.WARNING,
                                           'Battery command outcome is uncertain'):
                log_exception(f'Battery command failed: {requested_mode.battery_mode}')
        else:
            prev_state.battery_commanded_mode = requested_mode.battery_mode
            if state.health.report_success('battery_command'):
                log_info('Battery command completed after previous failure')


async def _execute_inverter_mode(
        state: _ControlState,
        prev_state: _PrevControl,
        power_controller: PowerController,
        requested_mode: ControlMode,
) -> None:
    """
    Execute inverter one-shot or live commands and record their outcomes.
    """
    inverter_mode_changed: bool = requested_mode.inverter_mode != prev_state.control_mode.inverter_mode
    if inverter_mode_changed and requested_mode.inverter_mode == InverterMode.ENABLE:
        try:
            await power_controller.enable_inverter()
        except Exception:
            prev_state.inverter_commanded_mode = InverterMode.UNKNOWN
            if state.health.report_failure('inverter_command', Severity.WARNING,
                                           'Inverter command outcome is uncertain'):
                log_exception(f'Inverter command failed: {requested_mode.inverter_mode}')
        else:
            prev_state.inverter_commanded_mode = requested_mode.inverter_mode
            if state.health.report_success('inverter_command'):
                log_info('Inverter command completed after previous failure')

    # These inverter modes require a keep-alive command on every iteration.
    # A failed command is logged and retried next iteration; the previous mode
    # records the request, not confirmation of the inverter's actual state.
    try:
        match requested_mode.inverter_mode:
            case InverterMode.DISABLE:
                await power_controller.disable_inverter(change_duration=Constants.CONTROL_DURATION)
            case InverterMode.ZERO_EXPORT:
                await power_controller.zero_export(change_duration=Constants.CONTROL_DURATION)
    except Exception:
        prev_state.inverter_commanded_mode = InverterMode.UNKNOWN
        if state.health.report_failure('inverter_command', Severity.WARNING,
                                       'Inverter command outcome is uncertain'):
            log_exception(f'Inverter command failed: {requested_mode.inverter_mode}')
    else:
        if requested_mode.inverter_mode in (InverterMode.DISABLE, InverterMode.ZERO_EXPORT):
            prev_state.inverter_commanded_mode = requested_mode.inverter_mode
            if state.health.report_success('inverter_command'):
                log_info('Inverter command completed after previous failure')


def _connect_dummy_controller(controller_connection: DummyControllerConnection) -> PowerController:
    return DummyPowerController(
        inverter_limit=controller_connection.inverter_limit,
        house_power=controller_connection.house_power,
        max_charge_param=controller_connection.max_charge_param,
        max_discharge_param=controller_connection.max_discharge_param,
    )


def _connect_dummy_pricer(pricer_connection: DummyPricerConnection) -> PowerPricer:
    return DummyPowerPricer(
        buy_price_min=pricer_connection.buy_price_min,
        buy_price_max=pricer_connection.buy_price_max,
        feed_in_price_discount_min=pricer_connection.feed_in_price_discount_min,
        feed_in_price_discount_max=pricer_connection.feed_in_price_discount_max,
        cur_price_is_estimate=pricer_connection.cur_price_is_estimate,
        demand_window=pricer_connection.demand_window,
    )


def _connect_dummy_consumer(consumer_connection: DummyConsumerConnection) -> PowerConsumer:
    return DummyPowerConsumer(
        voltage=consumer_connection.voltage,
        current=consumer_connection.current,
        power=consumer_connection.power,
        on=consumer_connection.on,
    )


def _connect_dummy_solar_forecaster(forecaster_connection: DummySolarForecasterConnection) -> SolarForecaster:
    return DummySolarForecaster(
        panel_capacity=forecaster_connection.panel_capacity,
        inverter_limit=forecaster_connection.inverter_limit,
    )


def _connect_modbus(controller_connection: ModbusControllerConnection) -> PowerController:
    """
    Establish a power controller modbus connection to the inverter.

    Does not change the control state in any way.

    Raises:
        ControlLoopError: a connection cannot be established.
    """
    addresses: list[ResolvedAddress] = resolve_addresses(split_addresses(controller_connection.address))
    if len(addresses) == 0:
        raise ControlLoopError('no controller address provided')

    # get ModbusTcpClient objects
    clients: list[ModbusTcpClient] = []  # coindexed with address
    errors: list[JSONDict] = []
    for address in addresses:
        client: ModbusTcpClient | None = None
        try:
            client: ModbusTcpClient = ModbusTcpClient(address.ip_address)
            if not client.connect():
                raise ConnectionError('Modbus TCP connection failed')
            clients.append(client)
        except Exception as err:
            if client is not None:
                client.close()
            errors.append({
                'host': address.ip_address,
                'mac_address': address.mac_address,
                'error': str(err),
            })
    # Fail if there are any errors
    if len(errors) > 0:
        for client in clients:
            client.close()
        raise ControlLoopError('could not connect Modbus TCP client', errors=errors)

    # Configure power controller
    master_client: ModbusTcpClient = clients[0]
    slave_clients: list[ModbusTcpClient] = clients[1:]
    devices: dict[str, ModbusDevice] = {
        'master': ModbusDevice(master_client, controller_connection.master_device_id),
    }
    slave_names: list[str]
    if len(slave_clients) == 1:
        slave_names = ['slave']
        devices['slave'] = ModbusDevice(slave_clients[0], controller_connection.slave_device_id)
    else:
        slave_names = []
        for slave_id, slave_client in enumerate(slave_clients, start=1):
            name = f'slave_{slave_id}'
            slave_names.append(name)
            devices[name] = ModbusDevice(slave_client, controller_connection.slave_device_id)
    devices['meter'] = ModbusDevice(master_client, controller_connection.meter_device_id)

    mac_addr_lookup: dict[str, str] = {
        address.ip_address: address.mac_address
        for address in addresses
    }

    controller = ModbusPowerController(
        Modbus(devices),
        master='master',
        meter='meter',
        slaves=slave_names,
        mac_addr_lookup=mac_addr_lookup,
    )

    return controller


def _connect_amber(pricer_connection: AmberPricerConnection) -> PowerPricer:
    """
    Establish a power pricer connection using Amber.

    Does not change the control state in any way.

    Raises:
        ControlLoopError: a connection cannot be established.
    """
    api_token = pricer_connection.api_token.strip()
    nmi = pricer_connection.nmi.strip()
    if api_token == '' or nmi == '':
        log_warn('No API token or NMI provided for Amber pricer')
        raise ControlLoopError('no API token or NMI provided for Amber pricer')
    try:
        amber_pricer = AmberPowerPricer(api_token, nmi)
    except Exception as err:
        raise ControlLoopError('could not connect Amber', errors=[str(err)])

    return amber_pricer


def _connect_tesla_wall_connector(consumer_connection: TeslaWallConnectorConnection) -> PowerConsumer:
    """
    Establish a power consumer connection using Tesla Wall Connector.

    Does not change the control state in any way.

    Raises:
        ControlLoopError: a connection cannot be established.
    """
    address: ResolvedAddress = resolve_addresses([consumer_connection.address])[0]
    try:
        return TeslaWallConnector(address.ip_address, address.mac_address)
    except Exception as err:
        raise ControlLoopError('could not connect Tesla Wall Connector', errors=[str(err)])


def _connect_tuya(consumer_connection: TuyaConnection) -> PowerConsumer:
    """
    Establish a power consumer connection using Tuya.

    Does not change the control state in any way.

    Raises:
        ControlLoopError: a connection cannot be established.
    """
    try:
        return TuyaPowerConsumer(
            access_id=consumer_connection.access_id,
            access_secret=consumer_connection.access_secret,
            device_id=consumer_connection.device_id,
            voltage_scale_factor=consumer_connection.voltage_scale_factor,
            current_scale_factor=consumer_connection.current_scale_factor,
            power_scale_factor=consumer_connection.power_scale_factor,
            cache_duration=consumer_connection.cache_duration,
        )
    except Exception as err:
        raise ControlLoopError('could not connect to the Tuya device', errors=[str(err)])


def _connect_open_meteo_forecaster(forecaster_connection: OpenMeteoConnection) -> SolarForecaster:
    """
    Construct an Open-Meteo solar forecaster without changing control state.

    Args:
        forecaster_connection: Open-Meteo forecast configuration.

    Returns:
        The configured solar forecaster.

    Raises:
        ControlLoopError: If the forecaster cannot be constructed.
    """
    try:
        return OpenMeteoForecaster(
            latitude=forecaster_connection.latitude,
            longitude=forecaster_connection.longitude,
            panel_orientation=forecaster_connection.panel_orientation,
            panel_tilt=forecaster_connection.panel_tilt,
            panel_capacity=forecaster_connection.panel_capacity,
            panel_temperature_coefficient=forecaster_connection.panel_temperature_coefficient,
            inverter_limit=forecaster_connection.inverter_limit,
            inverter_efficiency=forecaster_connection.inverter_efficiency,
        )
    except Exception as err:
        raise ControlLoopError('could not connect Open-Meteo', errors=[str(err)])


def _update_listeners(listeners: Iterable[LoopListener]) -> None:
    """
    Schedule an update on each listener.

    WARNING:
        * The given iterable should not be modified during iteration, i.e.
          this function should be given a copy of the list of listeners.
        * Do not hold the connections or cache lock while scheduling listener updates,
          as listeners may need to acquire it themselves.
    """
    for listener in listeners:
        asyncio.create_task(listener.update())


class PowerRegister(ReadOnlyRegister):
    """
    Expose a power status field as a read-only register.
    """

    def __init__(self, field_name: str, register_type: RegisterType) -> None:
        self._field_name = field_name
        super().__init__(register_type)

    async def _get(self) -> RegisterValue:
        return getattr(await get_power_status(), self._field_name)


class PriceRegister(ReadOnlyRegister):
    """
    Expose a current electricity price field as a read-only register.
    """

    def __init__(self, field_name: str, register_type: RegisterType) -> None:
        self._field_name = field_name
        super().__init__(register_type)

    async def _get(self) -> RegisterValue:
        return getattr(await get_price_now(), self._field_name)


class ConsumerRegister(ReadOnlyRegister):
    """
    Expose a consumer status field as a read-only register.
    """

    def __init__(self, consumer: PowerConsumer, field_name: str, register_type: RegisterType) -> None:
        self._field_name = field_name
        self._consumer = consumer
        super().__init__(register_type)

    async def _get(self) -> RegisterValue:
        return getattr(await self._consumer.get_status(), self._field_name)


async def _reconfigure_registers(state: _ControlState) -> None:
    """
    Updates the control loop register bank as per currently available delegates.
    Assumes the connections lock is held.
    """

    # Add status/battery and status/inverter registers
    registers: dict[str, Register] = {
        'status/battery/mode': CallRegister(lambda: _CONTROL_STATE.control.control_mode.battery_mode.name),
        'status/battery/policy': CallRegister(lambda: _CONTROL_STATE.control.control_mode.battery_policy.name),
        'status/battery/start_charge_price_threshold': CallRegister(
            lambda: _CONTROL_STATE.control.control_mode.start_charge_price_threshold),
        'status/battery/stop_charge_price_threshold': CallRegister(
            lambda: _CONTROL_STATE.control.control_mode.stop_charge_price_threshold),

        'status/inverter/mode': CallRegister(lambda: _CONTROL_STATE.control.control_mode.inverter_mode.name),
        'status/inverter/policy': CallRegister(lambda: _CONTROL_STATE.control.control_mode.inverter_policy.name),
        'status/inverter/enable_export_price_threshold': CallRegister(
            lambda: _CONTROL_STATE.control.control_mode.enable_export_price_threshold),
        'status/inverter/disable_export_price_threshold': CallRegister(
            lambda: _CONTROL_STATE.control.control_mode.disable_export_price_threshold),
    }

    # Add status/power registers
    f: Field
    for f in fields(PowerStatus):
        f_type: RegisterType = check_type(f.type)
        registers[f'status/power/{f.name}'] = PowerRegister(f.name, f_type)
    for consumer_name, consumer in state.connections.consumers.items():
        for f in fields(ConsumerStatus):
            try:
                reg_type: RegisterType = check_type(f.type)
            except TypeError:
                continue
            registers[f'status/power/consumers/{consumer_name}/{f.name}'] = \
                ConsumerRegister(consumer, f.name, reg_type)
        for prop_name, prop_type in _get_dataclass_properties(ConsumerStatus):
            try:
                reg_type: RegisterType = check_type(prop_type)
            except TypeError:
                continue
            registers[f'status/power/consumers/{consumer_name}/{prop_name}'] = \
                ConsumerRegister(consumer, prop_name, reg_type)
    for f in fields(Price):
        if f.name in ('start_time', 'end_time'):
            continue
        f_type: RegisterType = check_type(f.type)
        registers[f'status/power/{f.name}'] = PriceRegister(f.name, f_type)

    # Add controller registers
    try:
        await _add_delegate_registers(state, registers)
    except Exception:
        # Do not expose any delegate registers after a partial reconfiguration.
        registers = {name: register for name, register in registers.items()
                     if not name.startswith(('controller/', 'consumer/'))}
        state.connections.registers = RegisterBank(registers)
        if state.health.report_failure('register_configuration', Severity.CAUTION,
                                       'Register bank reconfiguration failed'):
            log_exception('Register bank reconfiguration failed')
    else:
        state.connections.registers = RegisterBank(registers)
        if state.health.report_success('register_configuration'):
            log_info('Register bank reconfiguration recovered')


async def _add_delegate_registers(state: _ControlState, registers: dict[str, Register]) -> None:
    """
    Add controller and consumer registers to the new register bank.

    Args:
        state: Current connection state.
        registers: Register mapping to extend.
    """
    if state.connections.controller is not None:
        controller_registers: RegisterBank = await state.connections.controller.get_registers()
        for name, register in controller_registers.items():
            registers[f'controller/{name}'] = register

    # Add power consumer registers
    for consumer_name, consumer in state.connections.consumers.items():
        consumer_registers: RegisterBank = await consumer.get_registers()
        for name, register in consumer_registers.items():
            registers[f'consumer/{consumer_name}/{name}'] = register


def _get_dataclass_properties(cls: type) -> Iterator[tuple[str, Any]]:
    """
    Iterate over properties defined on a class and their return types.

    Args:
        cls: Class whose properties are to be inspected.

    Yields:
        Property name and annotated getter return type.
    """
    for name, member in getmembers(cls):
        if isinstance(member, property) and member.fget is not None:
            prop_type = get_type_hints(member.fget)['return']
            yield name, prop_type


def _get_settings(state: _ControlState) -> Settings:
    """
    Build settings from the current control state.

    The caller must hold the connections and control-settings locks.

    Args:
        state: Current control state.

    Returns:
        Settings representing the current connections and control configuration.
    """
    control_mode = state.control.control_mode
    return Settings(
        controller=state.connections.controller_settings,
        pricer=state.connections.pricer_settings,
        consumers=state.connections.consumers_settings,
        forecaster=state.connections.forecaster_settings,
        database=state.connections.database_settings,

        battery_mode=control_mode.battery_mode,
        inverter_mode=control_mode.inverter_mode,
        battery_policy=control_mode.battery_policy,
        inverter_policy=control_mode.inverter_policy,

        disable_export_price_threshold=control_mode.disable_export_price_threshold,
        enable_export_price_threshold=control_mode.enable_export_price_threshold,

        start_charge_price_threshold=control_mode.start_charge_price_threshold,
        stop_charge_price_threshold=control_mode.stop_charge_price_threshold,

        registers_to_log=state.registers_to_log_str,
    )


async def _save_settings() -> None:
    """
    Persist settings across restarts.

    Acquire the connections lock before the persistence lock, as callers may
    already hold the connections lock. Serialize snapshots and writes so an
    older save cannot overwrite newer settings.
    """
    async with _connections_state():
        async with _CONTROL_STATE.settings_persistence.lock:
            settings_path = _CONTROL_STATE.settings_persistence.path
            if settings_path is None:
                return

            async with _control_settings_state():
                settings = _get_settings(_CONTROL_STATE)

            try:
                with open(settings_path, 'w') as file:
                    print(settings.model_dump_json(), file=file)
            except Exception as err:
                log_error(f'Error saving settings: {err!r}')


async def _load_settings() -> bool:
    """
    Load the persisted settings.

    Returns:
        True if settings were loaded successfully, False otherwise.
    """
    settings_path = _CONTROL_STATE.settings_persistence.path
    if settings_path is not None:
        try:
            with open(settings_path, 'r') as file:
                json_string = file.read()
            settings = Settings.model_validate_json(json_string)
            await configure_from_settings(settings)
            return True
        except Exception as err:
            log_error(f'Error loading settings: {err!r}')
    return False


# Initialise global state after the cache delegates have been defined.
_CONTROL_STATE: _ControlState = _ControlState()
