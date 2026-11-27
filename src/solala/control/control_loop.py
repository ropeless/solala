import asyncio
import json
import math
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable, Iterator, Mapping, Sequence
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass, field
from datetime import datetime, UTC, date
from functools import partial
from logging import INFO
from pathlib import Path

from psycopg import DatabaseError
from pymodbus.client import ModbusTcpClient

from solala.constants import Constants, GUI_TIMESTAMP_FORMAT
from solala.control.control_health import ControlHealth, HealthIssue, Severity
from solala.control.control_loop_error import ControlLoopError
from solala.control.loop_listener import LoopListener
from solala.control.modes_and_policies import BatteryMode, InverterMode, BatteryPolicy, InverterPolicy, ControlMode
from solala.control.power_consumer_manager import ConsumerReadOperation, PowerConsumerManager
from solala.control.register_manager import RegisterManager
from solala.control.resolve_addresses import ResolvedAddress, resolve_addresses
from solala.database.solala_database import SolalaDatabase, Measurement
from solala.database.solala_database_connections import SolalaDatabaseConnections
from solala.delegates.power_consumer.dummy_power_consumer.dummy_power_consumer import DummyPowerConsumer
from solala.delegates.power_consumer.matter_power_consumer.matter_power_consumer import MatterPowerConsumer
from solala.delegates.power_consumer.power_consumer import PowerConsumer, ConsumerStatus
from solala.delegates.power_consumer.tesla_wall_connector.tesla_wall_connector import TeslaWallConnector
from solala.delegates.power_consumer.tuya_cloud_power_consumer.tuya_cloud_power_consumer import TuyaCloudPowerConsumer
from solala.delegates.power_consumer.tuya_local_power_consumer.tuya_local_power_consumer import TuyaLocalPowerConsumer
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
from solala.register_bank import RegisterBank, EMPTY_REGISTER_BANK
from solala.settings import Settings, AmberPricerConnection, ModbusControllerConnection, TeslaWallConnectorConnection, \
    ControllerConnection, PricerConnection, ConsumerConnection, DummyControllerConnection, DummyPricerConnection, \
    DummyConsumerConnection, ForecasterConnection, OpenMeteoConnection, DummySolarForecasterConnection, \
    DatabaseConnection, TuyaCloudConnection, TuyaLocalConnection, MatterConnection
from solala.utils.json_extras import JSONDict, JSONValue
from solala.utils.lifecycle_cache import LifecycleCache, LifecycleReturn, error, interim, read_cache_for_refresh, valid
from solala.utils.ordered_async_rlock import OrderedAsyncRLock
from solala.utils.string_extras import split_addresses
from solala.utils.time_extras import now, local_time_zone
from solala.utils.type_extras import check_num

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
    Track the previous request and outcomes of control commands.

    Attributes:
        controller: Controller associated with the tracked state.
        control_mode: Last effective request, used to detect mode changes.
        battery_commanded_mode: Last successful battery command, or UNKNOWN
            after a failure; not independently verified hardware state.
        inverter_commanded_mode: Last successful inverter command, or UNKNOWN
            after a failure; not independently verified hardware state.
        failed_battery_mode: Most recent failed battery request, retained to
            prevent automatic repetition of an uncertain one-shot command.
        failed_inverter_mode: Most recent failed inverter request, retained
            for the same purpose when inverter ENABLE fails.
    """
    controller: PowerController | None = None
    control_mode: ControlMode = field(default_factory=ControlMode)
    battery_commanded_mode: BatteryMode = BatteryMode.UNKNOWN
    inverter_commanded_mode: InverterMode = InverterMode.UNKNOWN
    failed_battery_mode: BatteryMode | None = None
    failed_inverter_mode: InverterMode | None = None

    def reset(self, controller: PowerController | None) -> None:
        """
        Reset tracked modes and policies when the controller changes.

        Args:
            controller: Controller associated with the new tracking state.
        """
        self.controller = controller
        self.battery_commanded_mode = BatteryMode.UNKNOWN
        self.inverter_commanded_mode = InverterMode.UNKNOWN
        self.failed_battery_mode = None
        self.failed_inverter_mode = None
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
            retry=Constants.PRICE_FORECAST_RETRY.total_seconds(),
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
            retry=Constants.PRICE_DEMAND_WINDOW_RETRY.total_seconds(),
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
            retry=Constants.SOLAR_FORECAST_RETRY.total_seconds(),
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
    consumers: dict[str, PowerConsumerManager] = field(default_factory=dict)
    closing_consumers: dict[str, asyncio.Task[None]] = field(default_factory=dict)
    shutting_down: bool = False
    database_connections: SolalaDatabaseConnections | None = None

    # Keep track of the settings used to connect to the solar power system.
    controller_settings: ControllerConnection | None = None
    pricer_settings: PricerConnection | None = None
    forecaster_settings: ForecasterConnection | None = None
    consumers_settings: dict[str, ConsumerConnection] = field(default_factory=dict)
    database_settings: DatabaseConnection | None = None

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

    The connections lock protects changes to the queue and settings path.
    """
    path: Path | None = None
    last_save: asyncio.Task[None] | None = None


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
    health: ControlHealth = field(default_factory=lambda: ControlHealth(log_event=_log_health_event))

    # Listener lists are used on the same asyncio event loop; synchronous updates and snapshots need no lock.
    control_loop_listeners: list[LoopListener] = field(default_factory=list)
    database_loop_listeners: list[LoopListener] = field(default_factory=list)

    # Internal control loop tracking variables.
    control_loop_running: bool = True
    control_changed: asyncio.Event = field(default_factory=asyncio.Event)
    database_write: bool = True
    iteration_start: datetime = field(default_factory=now)  # used for control-loop scheduling
    last_control_step: datetime = field(default_factory=now)  # last completed control-step attempt

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

    def reset_consumer(self, consumer_name: str, consumer: PowerConsumerManager | None,
                       settings: ConsumerConnection | None, *, keep_settings: bool = False) -> None:
        if consumer is None:
            assert settings is None
            self.connections.consumers.pop(consumer_name, None)
            if not keep_settings:
                self.connections.consumers_settings.pop(consumer_name, None)
            self.health.report_success(f'consumer_status:{consumer_name}')
            self.health.report_success(f'consumer_registers:{consumer_name}')
        else:
            assert settings is not None
            self.connections.consumers[consumer_name] = consumer
            self.connections.consumers_settings[consumer_name] = settings

    def report_consumer_read(
            self, name: str, manager: PowerConsumerManager, operation: ConsumerReadOperation,
            read_error: Exception | None,
    ) -> None:
        """
        Translate a consumer worker's completed attempt into a health report.

        The worker supplies the read outcome. This callback checks that the
        manager is still registered under the name before forwarding it to
        ControlHealth.

        Args:
            name: Registered consumer name.
            manager: Manager that completed the read.
            operation: Status read or register discovery.
            read_error: Exception from the attempt, or None on success.
        """
        if self.connections.consumers.get(name) is not manager:
            return
        key = f'consumer_{operation}:{name}'
        if read_error is None:
            self.health.report_success(key, log_message=f'Consumer {name!r} {operation} recovered')
        else:
            message = f'Consumer {name!r} {operation} unavailable'
            self.health.report_failure(key, Severity.CAUTION, message, log_message=f'{message}: {read_error!r}')

    def reset_database(self, database: SolalaDatabaseConnections | None,
                       settings: DatabaseConnection | None) -> None:
        assert (database is None) == (settings is None)
        self.connections.database_connections = database
        self.connections.database_settings = settings


_LOG_SRC = '[control loop] '  # prefix for log messages


def get_control_health() -> tuple[Severity, tuple[HealthIssue, ...]]:
    """
    Read the control loop's operational health for the master alarm.

    This synchronous accessor returns reports already collected on the control
    event loop. The alarm reads heartbeat freshness separately.

    Returns:
        Current highest severity and immutable issue snapshots.
    """
    return _CONTROL_STATE.health.snapshot()


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


def _log_health_event(level: int, message: str, traceback: bool) -> None:
    """
    Forward a health diagnostic to the application's log.
    """
    if level == INFO:
        log_info(message)
    elif traceback:
        log_exception(message)
    else:
        log_error(message)


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
    Shutdown stops the database task and closes the open connections.
    If `settings_path` is provided, the settings file retains the configuration
    for the next run.

    Args:
        settings_path: Path to the settings file. Startup saves only after
            a complete configuration succeeds.

        settings: Configuration to use when no settings file is provided or
            when saved settings cannot be read or applied.

        force_settings: If True and `settings` is provided, use it directly
            without reading the settings file. Otherwise, try saved settings first.

        database_write: If False, the writing to the database is disabled. This is useful for testing.
    """

    # Prepare to run the control loop.
    _CONTROL_STATE.control_loop_running = True
    _CONTROL_STATE.database_write = database_write
    _CONTROL_STATE.settings_persistence.path = None
    path = Path(settings_path) if settings_path is not None else None

    database_task: asyncio.Task[None] | None = None
    try:
        # Include startup in the clean-up scope in case configuration fails partway through.
        await _configure_startup(path, settings, force_settings)
        database_task = asyncio.create_task(_database_loop())
        await _control_loop()
    finally:
        await _await_task_completion(asyncio.create_task(_shutdown_control_loop(database_task)))


# =============================================================================
#  Control loop interaction
# =============================================================================


def loop_check_overdue() -> float:
    """
    The control loop is expected to complete a step every `Constants.LOOP_TIME` seconds.
    Return the number of seconds past the next expected completion, i.e.
    `max(0, now - (last_control_step + Constants.LOOP_TIME))`.

    Returns:
        The number of seconds the loop check is overdue (a small number if running normally).
    """
    # The timestamp is updated on the same event loop; no lock is needed.
    return max(
        0,
        now().timestamp() - (_CONTROL_STATE.last_control_step.timestamp() + Constants.LOOP_TIME.total_seconds())
    )


def exit_control_loop() -> None:
    """
    Request control-loop shutdown and wake the control loop.
    """
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

    # Initialise control modes
    await set_control(
        battery_mode=settings.battery_mode,
        inverter_mode=settings.inverter_mode,
        battery_policy=settings.battery_policy,
        inverter_policy=settings.inverter_policy,
        fixed_limit_pct=settings.fixed_limit_pct,
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

    This is not a verified hardware state. Inverter DISABLE, FIXED_LIMIT and ZERO_EXPORT
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
                _CONTROL_STATE.health.report_failure(
                    'power_status', Severity.CAUTION, 'Power status unavailable: controller disconnected',
                    log_message='Power update not available. Error: power controller not connected',
                )
            else:
                try:
                    status = await controller.get_status()
                except Exception:
                    cache.last_power = _NO_POWER
                    _CONTROL_STATE.health.report_failure(
                        'power_status', Severity.CAUTION, 'Power status could not be read',
                        log_message='Power status update failed', traceback=True,
                    )
                else:
                    cache.last_power = status
                    cache.last_power_valid = True
                    _CONTROL_STATE.health.report_success(
                        'power_status', log_message='Power status recovered after previous failure',
                    )
            return cache.last_power


def get_register_bank() -> RegisterBank:
    """
    Return the current immutable mapping of known registers.

    Register values are obtained separately and may change or become
    unavailable after the bank is returned.

    Subsequent calls to this function may return a different register
    bank when delegates change or publish newly discovered registers.
    """
    return _REGISTERS.get_register_bank()


def request_consumer_register_discovery() -> None:
    """
    Request missing register definitions from active consumer managers.
    """
    for consumer in _CONTROL_STATE.connections.consumers.values():
        consumer.request_register_discovery()


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
    Request consumer status and return the readings available immediately.

    Returns:
        A mapping from consumer names to their available status readings.
    """
    async with _connections_state() as connections:
        return {
            name: status
            for name, consumer in connections.consumers.items()
            if (status := consumer.try_get_status()) is not None
        }


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
    async with asyncio.TaskGroup() as group:
        control = group.create_task(get_control_mode())
        power = group.create_task(get_power_status())
        price = group.create_task(read_cache_for_refresh(
            get_price_now, 'Current-price cache was invalidated during status refresh',
        ))
        consumers = group.create_task(get_consumers_status())

    power_status = power.result()
    consumers_status = consumers.result()
    power_json: JSONDict = power_status.to_json()
    if len(consumers_status) > 0:
        power_json: dict[str, JSONValue] = dict(power_json)
        power_json['consumer'] = {
            consumer: status.to_json()
            for consumer, status in consumers_status.items()
        }
        total = sum(check_num(consumer.power) for consumer in consumers_status.values())
        house_power = power_status.house_power
        power_json['consumer_total'] = total
        power_json['consumer_remaining'] = house_power - total

    return {
        'control': control.result().to_json(),
        'power': power_json,
        'price': price.result().to_json(datetime_format=GUI_TIMESTAMP_FORMAT, include_time=False),
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
        return error(
            f'Solar forecast not available for {day.strftime("%Y-%m-%d")}. Error: solar forecaster not connected')

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
        # mode and policy parameters
        fixed_limit_pct: float | None = None,
        disable_export_price_threshold: float | None = None,
        enable_export_price_threshold: float | None = None,
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
        fixed_limit_pct: Fixed inverter output limit as a percentage of rated power, from 0 to 100.
        disable_export_price_threshold: Feed-in price below which export is disabled.
        enable_export_price_threshold: Feed-in price above which export is enabled.
        start_charge_price_threshold: Buy price below which forced charging starts.
        stop_charge_price_threshold: Buy price above which forced charging stops.

    Raises:
        ControlLoopError: If the fixed limit is invalid or price thresholds are non-finite or not strictly ordered.
    """
    if fixed_limit_pct is not None and (
            not math.isfinite(fixed_limit_pct) or not 0 <= fixed_limit_pct <= 100
    ):
        raise ControlLoopError('fixed inverter limit must be a finite percentage from 0 to 100')

    for name, threshold in (
            ('disable_export_price_threshold', disable_export_price_threshold),
            ('enable_export_price_threshold', enable_export_price_threshold),
            ('start_charge_price_threshold', start_charge_price_threshold),
            ('stop_charge_price_threshold', stop_charge_price_threshold),
    ):
        if threshold is not None and not math.isfinite(threshold):
            raise ControlLoopError(f'{name} must be finite')

    async with _persist_settings_change():
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
            if fixed_limit_pct is not None:
                control_mode.fixed_limit_pct = fixed_limit_pct

            control_mode.disable_export_price_threshold = disable_export_price_threshold
            control_mode.enable_export_price_threshold = enable_export_price_threshold
            control_mode.start_charge_price_threshold = start_charge_price_threshold
            control_mode.stop_charge_price_threshold = stop_charge_price_threshold

            control_json = control_mode.to_json()

        # Wake the loop promptly; the next step will copy the settings.
        _CONTROL_STATE.control_changed.set()

    log_info(f'Control: {json.dumps(control_json)}')


# =============================================================================
#  Connection management for power control and price
# =============================================================================

def _log_connection_outcome(message: str, *, failed: bool = False) -> None:
    """
    Log a connection outcome without letting logger failures affect the caller.
    """
    logger = log_error if failed else log_info
    try:
        logger(message)
    except Exception:
        pass


@contextmanager
def _report_connection_errors(operation: str, delegate: str) -> Iterator[None]:
    """
    Log failures and expose them through the connection API.
    """
    try:
        yield
    except asyncio.CancelledError:
        _log_connection_outcome(f'{operation.capitalize()} cancelled for {delegate}')
        raise
    except Exception as err:
        detail = f'could not {operation} {delegate}'
        _log_connection_outcome(f'{detail}: {err!r}', failed=True)
        if isinstance(err, ControlLoopError):
            raise
        raise ControlLoopError(detail, errors={'error': repr(err)}) from err


@asynccontextmanager
async def _prepare_delegate(close: Callable[[], Awaitable[None]]) -> AsyncIterator[None]:
    """
    Close a prepared delegate if work fails before it is installed.
    """
    try:
        yield
    except (Exception, asyncio.CancelledError) as err:
        try:
            await close()
        except Exception as close_error:
            err.add_note(f'Failed to close prepared delegate: {close_error!r}')
        raise


async def connect_controller(controller_connection: ControllerConnection) -> None:
    """
    Connect or replace the power controller using the given settings.

    Log the outcome. Task cancellation propagates after being logged.

    Args:
        controller_connection: Power controller connection configuration.

    Raises:
        ControlLoopError: If the power controller cannot be connected.
    """
    with _report_connection_errors('connect', 'power controller'):
        replacement_error: Exception | asyncio.CancelledError | None = None
        async with _persist_settings_change() as connections:
            _require_connection_setup(connections)
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

            previous_detached = False
            try:
                async with _prepare_delegate(controller.close):
                    connection_info = json.dumps(controller.get_connection_info())
                    previous_controller = connections.controller
                    if previous_controller is not None:
                        await previous_controller.close()
                        await _CONTROL_STATE.reset_controller(None, None)
                        previous_detached = True
                        await _REGISTERS.update_controller(None)
                    await _REGISTERS.update_controller(controller)
            except (Exception, asyncio.CancelledError) as err:
                if not previous_detached:
                    raise
                # Save the disconnected state before reporting the replacement failure.
                replacement_error = err
            else:
                await _CONTROL_STATE.reset_controller(controller, controller_connection)
        if replacement_error is not None:
            raise replacement_error
        _log_connection_outcome(f'Power controller connection: {connection_info}')


async def disconnect_controller() -> None:
    """
    Close the power controller connection.

    Log the outcome, including when no controller is connected. Task
    cancellation propagates after being logged.

    Raises:
        ControlLoopError: If the power controller cannot be disconnected.
    """
    with _report_connection_errors('disconnect', 'power controller'):
        async with _persist_settings_change() as connections:
            controller = connections.controller
            if controller is not None:
                await controller.close()
                await _CONTROL_STATE.reset_controller(None, None)
            await _REGISTERS.update_controller(None)
        _log_connection_outcome(
            'Power controller disconnected' if controller is not None else 'Power controller already disconnected',
        )


async def connect_pricer(pricer_connection: PricerConnection) -> None:
    """
    Connect or replace the power pricer using the given settings.

    Log the outcome. Task cancellation propagates after being logged.

    Args:
        pricer_connection: Power pricer connection configuration.

    Raises:
        ControlLoopError: If the power pricer cannot be connected.
    """
    with _report_connection_errors('connect', 'power pricer'):
        async with _persist_settings_change() as connections:
            _require_connection_setup(connections)
            pricer: PowerPricer

            if pricer_connection.type == DummyPricerConnection.TYPE:
                assert isinstance(pricer_connection, DummyPricerConnection)
                pricer = _connect_dummy_pricer(pricer_connection)
            elif pricer_connection.type == AmberPricerConnection.TYPE:
                assert isinstance(pricer_connection, AmberPricerConnection)
                pricer = _connect_amber(pricer_connection)
            else:
                raise ControlLoopError('unknown pricer connection type', errors={'type': pricer_connection.type})

            async with _prepare_delegate(pricer.close):
                connection_info = json.dumps(pricer.get_connection_info())
                previous_pricer = connections.pricer
                if previous_pricer is not None:
                    await previous_pricer.close()
            await _CONTROL_STATE.reset_pricer(pricer, pricer_connection)
        _log_connection_outcome(f'Power pricer connection: {connection_info}')


async def disconnect_pricer() -> None:
    """
    Close the power pricer connection.

    Log the outcome, including when no pricer is connected. Task
    cancellation propagates after being logged.

    Raises:
        ControlLoopError: If the power pricer cannot be disconnected.
    """
    with _report_connection_errors('disconnect', 'power pricer'):
        async with _persist_settings_change() as connections:
            pricer = connections.pricer
            if pricer is not None:
                await pricer.close()
                await _CONTROL_STATE.reset_pricer(None, None)
        _log_connection_outcome('Power pricer disconnected' if pricer is not None else 'Power pricer already disconnected')


async def connect_consumer(name: str, consumer_connection: ConsumerConnection) -> None:
    """
    Connect a power consumer using a vacant consumer name.

    Successful return means the consumer is registered and its manager is
    available to the register manager. If registration fails, the consumer
    is left unregistered and any prepared delegate is closed.
    Cancellation propagates after cleanup. Settings persistence and logging
    are best-effort once the consumer is registered.

    Args:
        name: Name identifying the consumer.
        consumer_connection: Power consumer connection configuration.

    Raises:
        ControlLoopError: If the consumer cannot be registered, including
            when its name is active or closing or shutdown is in progress.
    """
    state = _CONTROL_STATE
    with _report_connection_errors('connect', f'power consumer {name!r}'):
        async with _connections_state() as connections:
            _require_vacant_consumer_name(connections, name)

        # Prepare the delegate outside the connections lock.
        if consumer_connection.type == DummyConsumerConnection.TYPE:
            assert isinstance(consumer_connection, DummyConsumerConnection)
            consumer = _connect_dummy_consumer(consumer_connection)
        elif consumer_connection.type == TeslaWallConnectorConnection.TYPE:
            assert isinstance(consumer_connection, TeslaWallConnectorConnection)
            consumer = _connect_tesla_wall_connector(consumer_connection)
        elif consumer_connection.type == MatterConnection.TYPE:
            assert isinstance(consumer_connection, MatterConnection)
            consumer = _connect_matter(consumer_connection)
        elif consumer_connection.type == TuyaCloudConnection.TYPE:
            assert isinstance(consumer_connection, TuyaCloudConnection)
            consumer = _connect_tuya_cloud(consumer_connection)
        elif consumer_connection.type == TuyaLocalConnection.TYPE:
            assert isinstance(consumer_connection, TuyaLocalConnection)
            consumer = _connect_tuya_local(consumer_connection)
        else:
            raise ControlLoopError(
                f'unknown consumer connection type for consumer: {name!r}',
                errors={'name': name, 'type': consumer_connection.type}
            )

        close_prepared = consumer.close
        connections_released = asyncio.Event()
        save: asyncio.Task[None] | None = None
        async with _prepare_delegate(lambda: close_prepared()):
            connection_info = json.dumps(consumer.get_connection_info())
            async with _connections_state() as connections:
                _require_vacant_consumer_name(connections, name)
                settings_path = state.settings_persistence.path
                settings: Settings | None = None
                if settings_path is not None:
                    async with _control_settings_state():
                        consumer_settings = connections.consumers_settings | {name: consumer_connection}
                        proposed = _get_settings(state).model_copy(update={'consumers': consumer_settings})
                        settings = proposed.model_copy(deep=True)

                # Once started, the manager owns the worker and delegate.
                new_manager = PowerConsumerManager(consumer, on_read_complete=partial(state.report_consumer_read, name))
                close_prepared = new_manager.close
                _REGISTERS.update_consumers(connections.consumers | {name: new_manager})
                state.reset_consumer(name, new_manager, consumer_connection)

                if settings_path is not None and settings is not None:
                    save = _queue_settings_write(state.settings_persistence, settings_path, settings, connections_released)

        # Registration now owns the manager, even if saving fails or is cancelled.
        connections_released.set()
        if save is not None:
            await _await_task_completion(save)
        _log_connection_outcome(f'Power consumer {name!r} connection: {connection_info}')


def _require_vacant_consumer_name(connections: _ConnectionsState, name: str) -> None:
    """
    Check that consumer registration is allowed and the name is available.

    The caller must hold the connections lock. This check does not reserve
    the name.

    Args:
        connections: Active and closing consumer connections.
        name: Consumer name to check.

    Raises:
        ControlLoopError: If the name is active or closing or shutdown is in progress.
    """
    _require_connection_setup(connections)
    if name in connections.consumers or name in connections.closing_consumers:
        raise ControlLoopError(f'consumer name {name!r} is already in use', errors={'name': name})


async def disconnect_consumer(name: str) -> None:
    """
    Detach and close the consumer before making its name available again.

    On successful return, the delegate has finished closing and its name has
    been released. Concurrent disconnect calls share the same close operation.

    Raises:
        ControlLoopError: If the consumer cannot be disconnected.
    """
    with _report_connection_errors('disconnect', f'power consumer {name!r}'):
        async with _connections_state() as connections:
            closing = connections.closing_consumers.get(name)
            if closing is None and name in connections.consumers:
                closing = _start_consumer_disconnect(connections, name, save_settings=True)
                _REGISTERS.update_consumers(connections.consumers)
        if closing is None:
            _log_connection_outcome(f'Power consumer {name!r} is already disconnected')
            return
        await _await_task_completion(closing)
        _log_connection_outcome(f'Power consumer {name!r} disconnected')


def _start_consumer_disconnect(
        connections: _ConnectionsState, name: str, *, save_settings: bool,
) -> asyncio.Task[None]:
    """
    Detach an active consumer and reserve its name until the close finishes.

    The caller must hold the connections lock.
    """
    consumer = connections.consumers[name]
    consumer.begin_close()
    _CONTROL_STATE.reset_consumer(name, None, None, keep_settings=not save_settings)
    closing = asyncio.create_task(_finish_consumer_disconnect(name, consumer, save_settings=save_settings))
    connections.closing_consumers[name] = closing
    return closing


async def _finish_consumer_disconnect(name: str, consumer: PowerConsumerManager, *, save_settings: bool) -> None:
    try:
        try:
            if save_settings:
                async with _persist_settings_change():
                    # Detachment already updated the settings under the connections lock.
                    pass
        finally:
            await consumer.close()
    finally:
        async with _connections_state() as connections:
            del connections.closing_consumers[name]


async def connect_forecaster(forecaster_connection: ForecasterConnection) -> None:
    """
    Connect or replace the solar forecaster using the given settings.

    Log the outcome. Task cancellation propagates after being logged.

    Args:
        forecaster_connection: Solar forecaster connection configuration.

    Raises:
        ControlLoopError: If the solar forecaster cannot be connected.
    """
    with _report_connection_errors('connect', 'solar forecaster'):
        async with _persist_settings_change() as connections:
            _require_connection_setup(connections)
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

            async with _prepare_delegate(forecaster.close):
                connection_info = json.dumps(forecaster.get_connection_info())
                previous_forecaster = connections.forecaster
                if previous_forecaster is not None:
                    await previous_forecaster.close()
            await _CONTROL_STATE.reset_forecaster(forecaster, forecaster_connection)
        _log_connection_outcome(f'Solar forecaster connection: {connection_info}')


async def disconnect_forecaster() -> None:
    """
    Close the solar forecaster connection.

    Log the outcome, including when no forecaster is connected. Task
    cancellation propagates after being logged.

    Raises:
        ControlLoopError: If the solar forecaster cannot be disconnected.
    """
    with _report_connection_errors('disconnect', 'solar forecaster'):
        async with _persist_settings_change() as connections:
            forecaster = connections.forecaster
            if forecaster is not None:
                await forecaster.close()
                await _CONTROL_STATE.reset_forecaster(None, None)
        _log_connection_outcome(
            'Solar forecaster disconnected' if forecaster is not None else 'Solar forecaster already disconnected',
        )


async def connect_database(database_connection: DatabaseConnection) -> None:
    """
    Replace the database pool without holding the connections lock while draining.

    Args:
        database_connection: Database connection configuration.
    """
    state = _CONTROL_STATE
    connections_released = asyncio.Event()
    async with state.database_lifecycle_lock:
        async with _connections_state() as connections:
            _require_connection_setup(connections)
        database_connections = SolalaDatabaseConnections(
            role=database_connection.role,
            password=database_connection.password,
            host=database_connection.host,
            port=database_connection.port,
            database_name=database_connection.database_name,
            min_pool_size=database_connection.min_pool_size,
            max_pool_size=database_connection.max_pool_size,
        )
        async with _connections_state() as connections:
            old_pool = connections.database_connections
            if old_pool is not None:
                old_pool.begin_close()
            state.reset_database(None, None)

        if old_pool is not None:
            await _close_database_pool(old_pool)

        async with _connections_state():
            state.reset_database(database_connections, database_connection)
            connection_info = database_connections.get_connection_info()
            _log_connection_outcome(f'Database connection: {json.dumps(connection_info)}')
            save = await _queue_current_settings_write(state, connections_released)

    connections_released.set()
    if save is not None:
        await _await_task_completion(save)


async def disconnect_database() -> None:
    """
    Close the database pool without blocking the connections lock during drain.
    """
    state = _CONTROL_STATE
    connections_released = asyncio.Event()
    async with state.database_lifecycle_lock:
        async with _connections_state() as connections:
            old_pool = connections.database_connections
            if old_pool is not None:
                old_pool.begin_close()
                state.reset_database(None, None)

        if old_pool is not None:
            await _close_database_pool(old_pool)

        async with _connections_state():
            save = await _queue_current_settings_write(state, connections_released)

    connections_released.set()
    if old_pool is not None:
        _log_connection_outcome('Database disconnected')
    if save is not None:
        await _await_task_completion(save)


# =============================================================================
#  Support functions
# =============================================================================


def _require_connection_setup(connections: _ConnectionsState) -> None:
    """
    Reject new registrations while shutdown owns the connection state.
    """
    if connections.shutting_down:
        raise ControlLoopError('cannot connect during control-loop shutdown')


async def _shutdown_control_loop(database_task: asyncio.Task[None] | None) -> None:
    """
    Stop background work, close open connections, and preserve the settings file.
    """
    _CONTROL_STATE.control_loop_running = False
    _log_connection_outcome('Starting control-loop shutdown')
    budget = Constants.MAX_SHUTDOWN_TIMEOUT.total_seconds()

    # This budget applies only to closing delegate connections and stopping
    # database logging. Control-loop housekeeping, including acquiring the
    # connections lock and detaching delegates, happens before the timer starts.
    # Pending settings writes are drained outside the timeout.
    async with _prepare_control_loop_cleanup(database_task) as closes:
        timeout = asyncio.timeout(budget)
        try:
            async with timeout:
                await _report_connection_closes(closes, 'control-loop shutdown')
        except TimeoutError:
            if not timeout.expired():
                raise
            _log_connection_outcome(f'Control-loop shutdown exceeded the {budget:g}-second budget', failed=True)
    if not timeout.expired():
        _log_connection_outcome('Finished control-loop shutdown')


async def _close_control_loop_resources(reason: str, database_task: asyncio.Task[None] | None = None) -> None:
    """
    Drain runtime resources during shutdown or before retrying startup.
    """
    async with _prepare_control_loop_cleanup(database_task) as closes:
        await _report_connection_closes(closes, reason)


@asynccontextmanager
async def _prepare_control_loop_cleanup(
        database_task: asyncio.Task[None] | None,
) -> AsyncIterator[Mapping[str, Awaitable[None]]]:
    """
    Detach resources for cleanup and drain settings writes before exiting.

    Yields:
        Resource names and their cleanup awaitables. The caller awaits them
        inside the context. Pending settings writes are drained on exit.
    """
    state = _CONTROL_STATE
    async with _connections_state() as connections:
        connections.shutting_down = True

    connections_released = asyncio.Event()
    settings_save: asyncio.Task[None] | None = None
    try:
        closes: dict[str, Awaitable[None]] = {}
        if database_task is not None:
            database_task.cancel()

        async with _connections_state() as connections:
            settings_save = await _prepare_shutdown_settings_save(state, connections_released)
            if connections.consumers:
                for name in tuple(connections.consumers):
                    _start_consumer_disconnect(connections, name, save_settings=False)
                _REGISTERS.update_consumers(connections.consumers)
            closes.update({
                f'power consumer {name!r}': task for name, task in connections.closing_consumers.items()
            })
            connections.consumers_settings.clear()
            controller, pricer, forecaster = connections.controller, connections.pricer, connections.forecaster
            # A replacement may have temporarily detached the pool.
            close_database = connections.database_connections is not None or state.database_lifecycle_lock.locked()
            if controller is not None:
                await state.reset_controller(None, None)
                await _REGISTERS.update_controller(None)
            if pricer is not None:
                await state.reset_pricer(None, None)
            if forecaster is not None:
                await state.reset_forecaster(None, None)

        connections_released.set()
        resources = {
            'power controller': controller, 'power pricer': pricer, 'solar forecaster': forecaster,
        }
        closes.update({
            name: resource.close() for name, resource in resources.items() if resource is not None
        })
        if close_database:
            closes['database pool'] = _shutdown_database_pool(state)
        if database_task is not None:
            closes['database logging'] = _stop_database_logging(database_task)
        yield closes
    finally:
        # If detachment was interrupted after queuing the snapshot, the
        # connections lock has still been released and the save can proceed.
        connections_released.set()
        try:
            if settings_save is not None:
                await _await_task_completion(settings_save)
        finally:
            async with _connections_state() as connections:
                connections.shutting_down = False


async def _shutdown_database_pool(state: _ControlState) -> None:
    """
    Close the pool after any database lifecycle operation finishes.
    """
    async with state.database_lifecycle_lock:
        async with _connections_state() as connections:
            pool = connections.database_connections
            if pool is None:
                return
            pool.begin_close()
            state.reset_database(None, None)
        await pool.close()


async def _stop_database_logging(database_task: asyncio.Task[None]) -> None:
    try:
        await database_task
    except asyncio.CancelledError:
        pass
    except Exception as err:
        _log_connection_outcome(f'Database logging failed during control-loop shutdown: {err!r}', failed=True)
    _log_connection_outcome('Stopped database logging during control-loop shutdown')


async def _report_connection_closes(closes: Mapping[str, Awaitable[None]], reason: str) -> None:
    """
    Await all supplied closes concurrently and log each outcome.
    """
    interrupted: set[asyncio.Future[None]] = set()

    def report(name: str, closing: asyncio.Future[None]) -> None:
        if closing.cancelled():
            if closing not in interrupted:
                _log_connection_outcome(f'Close cancelled for {name} during {reason}', failed=True)
        elif (err := closing.exception()) is not None:
            _log_connection_outcome(f'Failed to close {name} during {reason}: {err!r}', failed=True)
        elif name != 'database logging':
            _log_connection_outcome(f'Closed {name} during {reason}')

    tasks = {asyncio.ensure_future(close): name for name, close in closes.items()}
    if not tasks:
        return
    for task, name in tasks.items():
        task.add_done_callback(partial(report, name))
    try:
        await asyncio.wait(tasks)
    except asyncio.CancelledError:
        for task, name in tasks.items():
            if not task.done():
                interrupted.add(task)
                _log_connection_outcome(f'Still waiting for {name} when {reason} was interrupted', failed=True)
                task.cancel()
        raise


async def _close_database_pool(pool: SolalaDatabaseConnections) -> None:
    """
    Complete pool shutdown even if the calling task is cancelled.

    Cancellation is propagated after the pool has finished closing, so the
    database lifecycle lock remains held throughout the transition.
    """
    await _await_task_completion(asyncio.create_task(pool.close()))


async def _await_task_completion(task: asyncio.Task[None]) -> None:
    """
    Wait for a task to finish before propagating caller cancellation.

    Shield the task from cancellation of the caller. If the task
    succeeds, propagate any deferred caller cancellation. If the task fails,
    propagate its exception.

    Args:
        task: The task that must finish before the caller can exit.
    """
    cancelled = False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            cancelled = True
    await task
    if cancelled:
        raise asyncio.CancelledError


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
                _CONTROL_STATE.health.report_failure(
                    'database_measurement', Severity.CAUTION, 'Database measurement could not be saved',
                    log_message='Database measurement failed', traceback=True,
                )
            else:
                _CONTROL_STATE.health.report_success(
                    'database_measurement', log_message='Database measurements recovered after previous failure',
                )

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
            state.health.report_failure(
                'control_step', Severity.WARNING, 'Control step failed',
                log_message='Control step failed', traceback=True,
            )
        else:
            state.health.report_success('control_step', log_message='Control step recovered after previous failure')
        # A completed attempt is a heartbeat even when its failure was handled.
        # Cancellation propagates before this point and must not refresh it.
        state.last_control_step = now()

        # Ancillary work must not prevent the next control iteration.
        try:
            async with _cache_state() as cache:
                cache.last_power_valid = False
        except Exception:
            log_exception('Power cache invalidation failed')

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
        original_mode = requested_mode.copy()
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
        state.health.report_failure(
            'battery_policy', Severity.CAUTION, 'Battery price policy could not be evaluated',
            log_message='Battery price policy failed', traceback=True,
        )
    else:
        state.health.report_success('battery_policy', log_message='Battery price policy issue resolved')
    # A policy must not repeat an uncertain one-shot command on every tick.
    # A manual request from UNKNOWN, however, is an explicit new attempt.
    battery_retry_suppressed = (prev_state.failed_battery_mode == requested_mode.battery_mode
                                and original_mode.battery_mode == BatteryMode.UNKNOWN)
    if not battery_retry_suppressed:
        await _execute_battery_mode(state, prev_state, controller, requested_mode)
    if prev_state.failed_battery_mode is not None and requested_mode.battery_mode == prev_state.failed_battery_mode:
        requested_mode.battery_mode = BatteryMode.UNKNOWN

    try:
        await _apply_inverter_policy(requested_mode, pricer_available)
    except Exception:
        # Preserve the last effective mode so that an active inverter safety
        # command still receives its keep-alive when price retrieval fails.
        if requested_mode.inverter_mode != InverterMode.FIXED_LIMIT:
            requested_mode.inverter_mode = prev_state.control_mode.inverter_mode
        state.health.report_failure(
            'inverter_policy', Severity.CAUTION, 'Inverter price policy could not be evaluated',
            log_message='Inverter price policy failed', traceback=True,
        )
    else:
        state.health.report_success('inverter_policy', log_message='Inverter price policy issue resolved')
    inverter_retry_suppressed = (prev_state.failed_inverter_mode == requested_mode.inverter_mode
                                 and original_mode.inverter_mode == InverterMode.UNKNOWN)
    if not inverter_retry_suppressed:
        await _execute_inverter_mode(state, prev_state, controller, requested_mode)
    inverter_one_shot_failed = requested_mode.inverter_mode == prev_state.failed_inverter_mode
    if inverter_one_shot_failed:
        requested_mode.inverter_mode = InverterMode.UNKNOWN

    async with _control_settings_state() as control_state:
        # Publish UNKNOWN only if no newer user request arrived during I/O.
        if (prev_state.failed_battery_mode is not None
                and control_state.control_mode.battery_mode == original_mode.battery_mode
                and control_state.control_mode.battery_policy == original_mode.battery_policy):
            control_state.control_mode.battery_mode = BatteryMode.UNKNOWN
        if (inverter_one_shot_failed
                and control_state.control_mode.inverter_mode == original_mode.inverter_mode
                and control_state.control_mode.inverter_policy == original_mode.inverter_policy):
            control_state.control_mode.inverter_mode = InverterMode.UNKNOWN
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
    if control_mode.inverter_mode == InverterMode.FIXED_LIMIT:
        if price.is_estimate or not math.isfinite(price.feed_in_price):
            raise ControlLoopError('A valid feed-in price is required to leave Fixed Limit')
        # Fixed Limit has no automatic mode to carry through the hysteresis band.
        if price.feed_in_price <= control_mode.enable_export_price_threshold:
            control_mode.inverter_mode = InverterMode.ZERO_EXPORT
        else:
            control_mode.inverter_mode = InverterMode.ENABLE
    elif price.feed_in_price < control_mode.disable_export_price_threshold:
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
            prev_state.failed_battery_mode = requested_mode.battery_mode
            state.health.report_failure(
                'battery_command', Severity.WARNING, 'Battery command outcome is uncertain',
                log_message=f'Battery command failed: {requested_mode.battery_mode}', traceback=True,
            )
        else:
            prev_state.battery_commanded_mode = requested_mode.battery_mode
            prev_state.failed_battery_mode = None
            state.health.report_success('battery_command', log_message='Battery command completed after previous failure')


async def _execute_inverter_mode(
        state: _ControlState,
        prev_state: _PrevControl,
        power_controller: PowerController,
        requested_mode: ControlMode,
) -> None:
    """
    Execute inverter one-shot or keep-alive commands and record their outcomes.
    """
    inverter_mode_changed: bool = requested_mode.inverter_mode != prev_state.control_mode.inverter_mode
    if inverter_mode_changed and requested_mode.inverter_mode == InverterMode.ENABLE:
        try:
            await power_controller.enable_inverter()
        except Exception:
            prev_state.inverter_commanded_mode = InverterMode.UNKNOWN
            prev_state.failed_inverter_mode = requested_mode.inverter_mode
            state.health.report_failure(
                'inverter_command', Severity.WARNING, 'Inverter command outcome is uncertain',
                log_message=f'Inverter command failed: {requested_mode.inverter_mode}', traceback=True,
            )
        else:
            prev_state.inverter_commanded_mode = requested_mode.inverter_mode
            prev_state.failed_inverter_mode = None
            state.health.report_success(
                'inverter_command', log_message='Inverter command completed after previous failure',
            )

    # These inverter modes require a keep-alive command on every iteration.
    # A failed command is logged and retried next iteration; the previous mode
    # records the request, not confirmation of the inverter's actual state.
    try:
        match requested_mode.inverter_mode:
            case InverterMode.DISABLE:
                await power_controller.disable_inverter(change_duration=Constants.CONTROL_DURATION)
            case InverterMode.FIXED_LIMIT:
                await power_controller.fixed_limit(
                    requested_mode.fixed_limit_pct,
                    change_duration=Constants.CONTROL_DURATION,
                )
            case InverterMode.ZERO_EXPORT:
                await power_controller.zero_export(change_duration=Constants.CONTROL_DURATION)
            case _:
                return
    except Exception:
        prev_state.inverter_commanded_mode = InverterMode.UNKNOWN
        message = 'Inverter command outcome is uncertain'
        command = requested_mode.inverter_mode.name
        if requested_mode.inverter_mode == InverterMode.FIXED_LIMIT:
            command = f'{command} ({requested_mode.fixed_limit_pct:g}%)'
            message = f'{message}: {command}'
        state.health.report_failure(
            'inverter_command', Severity.WARNING, message,
            log_message=f'Inverter command failed: {command}', traceback=True,
        )
    else:
        prev_state.inverter_commanded_mode = requested_mode.inverter_mode
        state.health.report_success('inverter_command', log_message='Inverter command completed after previous failure')

    # A keep-alive request supersedes any earlier one-shot request, even if
    # this attempt fails. The command warning still tracks its outcome.
    prev_state.failed_inverter_mode = None


def _connect_dummy_controller(controller_connection: DummyControllerConnection) -> PowerController:
    return DummyPowerController(
        inverter_limit=controller_connection.inverter_limit,
        house_power=controller_connection.house_power,
        max_charge_param=controller_connection.max_charge_param,
        max_discharge_param=controller_connection.max_discharge_param,
        failure=controller_connection.failure,
    )


def _connect_dummy_pricer(pricer_connection: DummyPricerConnection) -> PowerPricer:
    return DummyPowerPricer(
        buy_price_min=pricer_connection.buy_price_min,
        buy_price_max=pricer_connection.buy_price_max,
        feed_in_price_discount_min=pricer_connection.feed_in_price_discount_min,
        feed_in_price_discount_max=pricer_connection.feed_in_price_discount_max,
        cur_price_is_estimate=pricer_connection.cur_price_is_estimate,
        demand_window=pricer_connection.demand_window,
        failure=pricer_connection.failure,
    )


def _connect_dummy_consumer(consumer_connection: DummyConsumerConnection) -> PowerConsumer:
    return DummyPowerConsumer(
        voltage=consumer_connection.voltage,
        current=consumer_connection.current,
        power=consumer_connection.power,
        on=consumer_connection.on,
        failure=consumer_connection.failure,
        can_switch=consumer_connection.can_switch,
        include_accumulated_energy=consumer_connection.include_accumulated_energy,
    )


def _connect_dummy_solar_forecaster(forecaster_connection: DummySolarForecasterConnection) -> SolarForecaster:
    return DummySolarForecaster(
        panel_capacity=forecaster_connection.panel_capacity,
        inverter_limit=forecaster_connection.inverter_limit,
        failure=forecaster_connection.failure,
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
        power_control_slaves=controller_connection.power_control_slaves,
        default_MinRsvPct=controller_connection.default_MinRsvPct,
        default_WMaxLimPct_RvrtTms=controller_connection.default_WMaxLimPct_RvrtTms,
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
        return TeslaWallConnector(
            address.ip_address,
            mac_address=address.mac_address,
            cache_duration=consumer_connection.cache_duration,
            timeout=consumer_connection.timeout,
        )
    except Exception as err:
        raise ControlLoopError('could not connect Tesla Wall Connector', errors=[str(err)])


def _connect_matter(consumer_connection: MatterConnection) -> PowerConsumer:
    """
    Construct a Matter consumer from explicitly supplied connection settings.
    """
    try:
        return MatterPowerConsumer(
            host=consumer_connection.host,
            port=consumer_connection.port,
            node_id=consumer_connection.node_id,
            endpoint_id=consumer_connection.endpoint_id,
            token=consumer_connection.token,
            secure=consumer_connection.secure,
            timeout=consumer_connection.timeout,
            cache_duration=consumer_connection.cache_duration,
        )
    except Exception as err:
        raise ControlLoopError('could not configure Matter consumer', errors=[str(err)])


def _connect_tuya_cloud(consumer_connection: TuyaCloudConnection) -> PowerConsumer:
    """
    Establish a power consumer connection using Tuya.

    Does not change the control state in any way.

    Raises:
        ControlLoopError: a connection cannot be established.
    """
    try:
        return TuyaCloudPowerConsumer(
            access_id=consumer_connection.access_id,
            access_secret=consumer_connection.access_secret,
            device_id=consumer_connection.device_id,
            voltage_scale_factor=consumer_connection.voltage_scale_factor,
            current_scale_factor=consumer_connection.current_scale_factor,
            power_scale_factor=consumer_connection.power_scale_factor,
            calibration_factor=consumer_connection.calibration_factor,
            cache_duration=consumer_connection.cache_duration,
            include_accumulated_energy=consumer_connection.include_accumulated_energy,
            connect_timeout=consumer_connection.connect_timeout,
            read_timeout=consumer_connection.read_timeout,
        )
    except Exception as err:
        raise ControlLoopError('could not connect to the Tuya device', errors=[str(err)])


def _connect_tuya_local(connection: TuyaLocalConnection) -> PowerConsumer:
    """
    Construct a Tuya LAN power consumer without connecting to the device.
    """
    try:
        return TuyaLocalPowerConsumer(
            host=connection.host,
            device_id=connection.device_id,
            local_key=connection.local_key,
            version=connection.version,
            calibration_factor=connection.calibration_factor,
            timeout=connection.timeout,
            cache_duration=connection.cache_duration,
        )
    except Exception as err:
        raise ControlLoopError('could not configure Tuya LAN consumer', errors=[str(err)])


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
        asyncio.create_task(_update_listener(listener))


async def _update_listener(listener: LoopListener) -> None:
    """
    Run a loop listener and log failures without interrupting dispatch.
    """
    try:
        await listener.update()
    except Exception:
        LOGGER.exception('Loop listener %s refresh failed', type(listener).__name__)


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

        fixed_limit_pct=control_mode.fixed_limit_pct,
    )


def _write_settings_file(settings_path: Path, settings: Settings) -> None:
    with open(settings_path, 'w') as file:
        print(settings.model_dump_json(), file=file)


async def _write_settings_in_thread(settings_path: Path, settings: Settings) -> None:
    try:
        await asyncio.to_thread(_write_settings_file, settings_path, settings)
    except Exception as err:
        log_error(f'Error saving settings: {err!r}')
    else:
        log_info('Settings file written')


def _queue_settings_write(
        persistence: _SettingsPersistenceState,
        path: Path,
        settings: Settings,
        connections_released: asyncio.Event,
) -> asyncio.Task[None]:
    """
    Append a snapshot in capture order while the connections lock is held.

    Args:
        persistence: Settings persistence state that owns the write queue.
        path: Destination settings file.
        settings: Snapshot to write.
        connections_released: Event the caller must set after releasing the
            connections lock. This write and later writes wait for the signal.

    Returns:
        Task that completes after the write attempt.
    """
    previous = persistence.last_save

    async def write() -> None:
        await connections_released.wait()
        if previous is not None and not previous.done():
            await asyncio.wait((previous,))
        await _write_settings_in_thread(path, settings)

    save = asyncio.create_task(write())
    persistence.last_save = save
    return save


async def _prepare_shutdown_settings_save(
        state: _ControlState, connections_released: asyncio.Event,
) -> asyncio.Task[None] | None:
    """
    Queue any explicit removals and return the last save shutdown must drain.

    The caller holds the connections lock and signals when it is released.
    """
    persistence = state.settings_persistence
    path = persistence.path
    if path is not None and state.connections.closing_consumers:
        async with _control_settings_state():
            settings = _get_settings(state).model_copy(deep=True)
        _queue_settings_write(persistence, path, settings, connections_released)
    persistence.path = None
    return persistence.last_save


@asynccontextmanager
async def _persist_settings_change() -> AsyncIterator[_ConnectionsState]:
    """
    Hold the connections lock for a change and snapshot, then write separately.

    Queue the snapshot before releasing the lock so writes stay ordered with
    consumer registration and the final shutdown save.
    """
    state = _CONTROL_STATE
    connections_released = asyncio.Event()
    async with _connections_state() as connections:
        yield connections
        save = await _queue_current_settings_write(state, connections_released)

    connections_released.set()
    if save is not None:
        await _await_task_completion(save)


async def _queue_current_settings_write(
        state: _ControlState, connections_released: asyncio.Event,
) -> asyncio.Task[None] | None:
    """
    Capture and queue the current settings while the connections lock is held.
    """
    persistence = state.settings_persistence
    path = persistence.path
    if path is None:
        return None
    async with _control_settings_state():
        settings = _get_settings(state).model_copy(deep=True)
    return _queue_settings_write(persistence, path, settings, connections_released)


async def _configure_startup(settings_path: Path | None, settings: Settings | None, force_settings: bool) -> None:
    """
    Apply saved or supplied settings with persistence disabled until startup succeeds.
    """
    loaded = False
    if settings_path is not None and (not force_settings or settings is None):
        saved = _load_settings(settings_path)
        if saved is not None:
            try:
                await configure_from_settings(saved)
            except Exception as err:
                _log_connection_outcome(f'Error applying saved settings: {err!r}', failed=True)
                if settings is None:
                    raise
                _log_connection_outcome('Closing partial startup connections before applying fallback settings')
                await _await_task_completion(asyncio.create_task(_close_control_loop_resources('startup rollback')))
            else:
                loaded = True

    if not loaded and settings is not None:
        await configure_from_settings(settings)

    if settings_path is None or (not loaded and settings is None):
        _CONTROL_STATE.settings_persistence.path = settings_path
        return

    async with _persist_settings_change():
        _CONTROL_STATE.settings_persistence.path = settings_path


def _load_settings(settings_path: Path) -> Settings | None:
    """
    Read and validate persisted settings before opening any connections.
    """
    try:
        return Settings.model_validate_json(settings_path.read_bytes())
    except (OSError, ValueError) as err:
        _log_connection_outcome(f'Error loading settings: {err!r}', failed=True)
        return None


# Initialise global state after the cache delegates have been defined.
_CONTROL_STATE: _ControlState = _ControlState()
_REGISTERS = RegisterManager(_CONTROL_STATE.control.control_mode, get_power_status, get_price_now)
