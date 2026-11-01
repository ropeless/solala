import asyncio
import copy
import json
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, UTC, timedelta, date
from pathlib import Path
from typing import Optional, List, Dict, Sequence, Iterable, AsyncIterator

from pymodbus.client import ModbusTcpClient

from solala.constants import Constants, TIMESTAMP_FORMAT
from solala.control_loop.errors import ControlLoopError
from solala.control_loop.loop_listener import LoopListener
from solala.control_loop.modes_and_policies import BatteryMode, InverterMode, BatteryPolicy, InverterPolicy, ControlMode
from solala.database.solala_database import SolalaDatabase, Measurement
from solala.database.solala_database_connections import SolalaDatabaseConnections
from solala.delegates.power_consumer.dummy_power_consumer.dummy_power_consumer import DummyPowerConsumer
from solala.delegates.power_consumer.power_consumer import PowerConsumer, ConsumerStatus
from solala.delegates.power_consumer.tesla_wall_connector.tesla_wall_connector import TeslaWallConnector
from solala.delegates.power_controller.dummy_power_controller.dummy_power_controller import DummyPowerController
from solala.delegates.power_controller.modbus_power_controller.modbus import Modbus, ModbusDevice
from solala.delegates.power_controller.modbus_power_controller.modbus_power_controller import ModbusPowerController
from solala.delegates.power_controller.power_controller import PowerController
from solala.delegates.power_controller.power_controller import PowerStatus
from solala.delegates.power_pricer.amber_power_pricer.amber_power_pricer import Price, AmberPowerPricer
from solala.delegates.power_pricer.dummy_power_pricer.dummy_power_pricer import DummyPowerPricer
from solala.delegates.power_pricer.power_pricer import PowerPricer
from solala.delegates.solar_forecaster.dummy_solar_forecaster.dummy_solar_forecaster import DummySolarForecaster
from solala.delegates.solar_forecaster.open_meteo_forecaster.open_meteo_forecaster import OpenMeteoForecaster
from solala.delegates.solar_forecaster.solar_forecast import SolarForecast
from solala.delegates.solar_forecaster.solar_forecaster import SolarForecaster, DailySolarForecast
from solala.delegates.solar_forecaster.weather_code import WeatherCode
from solala.logger import LOGGER
from solala.settings import Settings, AmberPricerConnection, ModbusControllerConnection, \
    TeslaWallConnectorConnection, ControllerConnection, PricerConnection, ConsumerConnection, \
    DummyControllerConnection, \
    DummyPricerConnection, DummyConsumerConnection, ForecasterConnection, OpenMeteoConnection, \
    DummySolarForecasterConnection, DatabaseConnection
from solala.utils.async_rlock import AsyncRLock
from solala.utils.datetime_extras import now, local_time_zone
from solala.utils.json import JSONDict, json_num
from solala.utils.network import find_ip_by_mac
from solala.utils.string_extras import split_addresses

_LOG_SRC = '[control loop] '  # prefix for log messages

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


@dataclass(frozen=True)
class _DateKey:
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
    controller: Optional[PowerController] = None
    control_mode: ControlMode = field(default_factory=ControlMode)

    def reset(self, controller: Optional[PowerController]) -> None:
        self.controller = controller
        self.control_mode.battery_mode = BatteryMode.UNKNOWN
        self.control_mode.inverter_mode = InverterMode.UNKNOWN
        self.control_mode.battery_policy = BatteryPolicy.MANUAL
        self.control_mode.inverter_policy = InverterPolicy.MANUAL


@dataclass
class _ControlState:
    # These are the work objects for accessing the solar power system
    controller: Optional[PowerController] = None
    pricer: Optional[PowerPricer] = None
    forecaster: Optional[SolarForecaster] = None
    consumers: Dict[str, PowerConsumer] = field(default_factory=dict)
    database_connections: Optional[SolalaDatabaseConnections] = None

    # Keep track of the settings use to connect to the solar power system
    controller_settings: Optional[ControllerConnection] = None
    pricer_settings: Optional[PricerConnection] = None
    forecaster_settings: Optional[ForecasterConnection] = None
    consumers_settings: Dict[str, ConsumerConnection] = field(default_factory=dict)
    database_settings: Optional[DatabaseConnection] = None

    # What the user is asking the control loop to do
    control_mode: ControlMode = field(default_factory=ControlMode)

    # Caches of status components

    last_power: PowerStatus = field(default_factory=lambda: _NO_POWER)
    last_power_valid: bool = False

    last_price: Price = _NO_PRICE
    next_price_check: datetime = _MIN_DATE

    last_price_forecast: Sequence[Price] = ()
    next_price_forecast_check: datetime = _MIN_DATE

    last_solar_forecast: Dict[_DateKey, DailySolarForecast] = field(default_factory=dict)
    next_solar_forecast_check: datetime = _MIN_DATE

    # Internal control loop tracking variables
    lock: AsyncRLock = field(default_factory=AsyncRLock)
    prev_state: _PrevControl = field(default_factory=_PrevControl)
    control_loop_running: bool = True
    listeners: List[LoopListener] = field(default_factory=list)
    settings_path: Optional[Path] = None  # for using persisted settings.
    iteration_start: datetime = field(default_factory=now)  # used to confirm the control loop is running

    @property
    def controller_connection_status(self) -> JSONDict:
        if self.controller is None:
            return _DISCONNECTED
        else:
            return self.controller.get_connection_status()

    @property
    def pricer_connection_status(self) -> JSONDict:
        if self.pricer is None:
            return _DISCONNECTED
        else:
            return self.pricer.get_connection_status()

    @property
    def forecaster_connection_status(self) -> JSONDict:
        if self.forecaster is None:
            return _DISCONNECTED
        else:
            return self.forecaster.get_connection_status()

    @property
    def consumers_connection_status(self) -> Dict[str, JSONDict]:
        return {
            name: consumer.get_connection_status()
            for name, consumer in self.consumers.items()
        }

    @property
    def database_connection_status(self) -> JSONDict:
        if self.database_connections is None:
            return _DISCONNECTED
        else:
            return self.database_connections.get_connection_status()

    def reset_controller(self, controller: Optional[PowerController], settings: Optional[ControllerConnection]) -> None:
        assert (controller is None) == (settings is None)
        self.controller = controller
        self.controller_settings = settings

        # Modes are now unknown, but leave the current policies in place
        self.control_mode.battery_mode = BatteryMode.UNKNOWN
        self.control_mode.inverter_mode = InverterMode.UNKNOWN

        # Invalidate cached status
        self.last_power = _NO_POWER
        self.last_power_valid = False

    def reset_pricer(self, pricer: Optional[PowerPricer], settings: Optional[PricerConnection]) -> None:
        assert (pricer is None) == (settings is None)
        self.pricer = pricer
        self.pricer_settings = settings

        # Invalidate cached status
        self.last_price: Price = _NO_PRICE
        self.next_price_check = _MIN_DATE
        self.last_price_forecast = ()
        self.next_price_forecast_check = _MIN_DATE

    def reset_forecaster(self, forecaster: Optional[SolarForecaster], settings: Optional[ForecasterConnection]) -> None:
        assert (forecaster is None) == (settings is None)
        self.forecaster = forecaster
        self.forecaster_settings = settings

        # Invalidate cached status
        self.last_price_forecast = ()
        self.next_solar_forecast_check = _MIN_DATE

    def reset_consumer(self, consumer_name: str, consumer: Optional[PowerConsumer],
                       settings: Optional[ConsumerConnection]) -> None:
        if consumer is None:
            assert settings is None
            self.consumers.pop(consumer_name, None)
            self.consumers_settings.pop(consumer_name, None)
        else:
            assert settings is not None
            self.consumers[consumer_name] = consumer
            self.consumers_settings[consumer_name] = settings

    def reset_database(self, database: Optional[SolalaDatabaseConnections],
                       settings: Optional[DatabaseConnection]) -> None:
        assert (database is None) == (settings is None)
        self.database_connections = database
        self.database_settings = settings


# Global control loop state
# For thread-safe access to the control state use `_control_state()`.
_CONTROL_STATE: _ControlState = _ControlState()


@asynccontextmanager
async def _control_state() -> AsyncIterator[_ControlState]:
    """
    Get exclusive access to the control state.

    This is a reentrant lock, i.e. the same task can acquire the lock multiple times.

    Usage:
    ```
    async with _control_state() as state:
        # read and write to state.
    ```

    Returns:
        The control state.
    """
    async with _CONTROL_STATE.lock:
        yield _CONTROL_STATE


# ============================================================================
#  Public control loop functions
# ============================================================================


async def control_loop(
        settings_path: Optional[Path | str] = None,
        settings: Optional[Settings] = None,
        force_settings: bool = False,
) -> None:
    """
    Execute the control loop.

    Multiple thread-safe functions are provided to manage the behaviour of the control loop.

    Call `exit_control_loop()` to gracefully terminate the control loop.

    Args:
        settings_path: Path to the settings file, if settings are to be persisted. If provided, the control
            loop will attempt to load settings from the file.

        settings: Settings object to use if the settings file cannot be loaded.

        force_settings: If True, the given settings object will always override any settings loaded from the file.
            Note that if settings are provided, they will override any settings loaded from the file. This includes
            modes and policies if the power controller is reloaded.
    """

    # Prepare to run the control loop.
    _CONTROL_STATE.control_loop_running = True

    # Configure from user settings
    loaded: bool = False
    if settings_path is not None:
        _CONTROL_STATE.settings_path = Path(settings_path)
        if not force_settings or settings is None:
            loaded = await _load_settings()
    if (not loaded or force_settings) and settings is not None:
        await configure_from_settings(settings)

    database_task = asyncio.create_task(_database_loop())
    await _control_loop()
    database_task.cancel()


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
    return max(0, now().timestamp() - (_CONTROL_STATE.iteration_start.timestamp() + Constants.LOOP_TIME))


def exit_control_loop() -> None:
    """
    Flag to exit the control loop on the next iteration.
    """
    # We are not concerned with race conditions, so we do not need to get the control loop lock.
    _CONTROL_STATE.control_loop_running = False


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
        disable_export_price_threshold=settings.disable_export_price_threshold,
        enable_export_price_threshold=settings.enable_export_price_threshold,
        start_charge_price_threshold=settings.start_charge_price_threshold,
        stop_charge_price_threshold=settings.stop_charge_price_threshold,
    )


async def get_settings() -> Settings:
    async with _control_state() as state:
        return _get_settings(state)


async def add_listener(listener: LoopListener) -> None:
    async with _control_state() as state:
        try:
            state.listeners.remove(listener)
        except ValueError:
            pass
        state.listeners.append(listener)


async def remove_listener(listener: LoopListener) -> None:
    async with _control_state() as state:
        try:
            state.listeners.remove(listener)
        except ValueError:
            pass


async def update_listeners() -> None:
    """
    Call `update` on all registered control loop listeners.
    """
    async with _control_state() as state:
        listeners = state.listeners.copy()
    # Update the listeners while not holding the control state lock.
    _update_listeners(listeners)


async def get_control_mode() -> ControlMode:
    """
    Get what the control loop is aiming to do for the user.
    """
    async with _control_state() as state:
        return copy.copy(state.control_mode)


async def get_prev_control_mode() -> ControlMode:
    """
    Get what the control loop last did for the user.
    """
    async with _control_state() as state:
        return copy.copy(state.prev_state.control_mode)


async def get_power_status() -> PowerStatus:
    async with _control_state() as state:
        if not state.last_power_valid:
            controller: Optional[PowerController] = state.controller
            if controller is None:
                LOGGER.error(f'{_LOG_SRC}Power update not available. Error: power controller not connected')
            else:
                state.last_power = await controller.get_status()
            state.last_power_valid = True
        return state.last_power


async def get_registers() -> Dict[str, int | float | str | bool]:
    """
    Get the values of all registers of the power controller.
    """
    async with _control_state() as state:
        if state.controller is None:
            LOGGER.error(f'{_LOG_SRC}Power registers not available. Error: power controller not connected')
            return {}
        else:
            return {
                register: value
                for register, value in await state.controller.get_registers()
            }


async def get_price_now() -> Price:
    """
    Get the current price from the power pricer.
    """
    async with _control_state() as state:
        price: Price = state.last_price
        pricer = state.pricer
        if pricer is None:
            LOGGER.error(f'{_LOG_SRC}Price update not available. Error: power pricer not connected')
            return price

        timestamp = now()
        if state.next_price_check <= timestamp:
            try:
                price: Price = await pricer.get_price()
                LOGGER.info(f'{_LOG_SRC}Updated current price: {price}')
                state.last_price = price
                if price.is_estimate:
                    # price is unstable - recheck is needed
                    delay = Constants.PRICE_SETTLE_CHECK
                    state.next_price_check = min(timestamp + timedelta(seconds=delay), price.end_time)
                    LOGGER.info(f'{_LOG_SRC}Current price is an estimate, recheck is scheduled')
                else:
                    # price is stable - no need to recheck for this period
                    state.next_price_check = price.end_time.astimezone(UTC)
            except Exception as err:
                LOGGER.error(f'{_LOG_SRC}Price update not available. Error: {err}')

        return price


async def get_price_now_no_estimate(max_tries: int = 10) -> Price:
    """
    Get the current price from the power pricer, looping until the price is not an estimate.

    The returned price may be an estimate if the pricer is not available or could not
    provide a non-estimate price within the given number of tries.
    """
    price: Price = await get_price_now()
    max_tries -= 1
    while price.is_estimate and max_tries > 1 and _CONTROL_STATE.pricer is not None:
        max_tries -= 1
        await asyncio.sleep(Constants.PRICE_SETTLE_CHECK)
        price = await get_price_now()
    return price


async def get_price_forecast() -> Sequence[Price]:
    """
    Get the forecast prices from the power pricer.

    Get the 30-minute price forecasts, in ascending order of time from now.
    Nominally this will return `Constants.PRICE_FORECAST_DURATION * 2` prices
    but may be less (or zero) if there is an error.

    Errors will be logged but should not raise an exception.
    """
    async with _control_state() as state:
        pricer = state.pricer
        if pricer is None:
            LOGGER.error(f'{_LOG_SRC}Price forecast not available. Error: power pricer not connected')
            return ()

        prices: Sequence[Price] = state.last_price_forecast
        needed_forecasts: int = Constants.PRICE_FORECAST_DURATION * 2  # convert hours to 30-minute forecasts.
        timestamp = now()
        if state.next_price_forecast_check <= timestamp or len(prices) == 0 or prices[0].end_time < timestamp:
            try:
                # Plus one to account for possible race condition (see below).
                prices: List[Price] = await pricer.get_price_forecast(needed_forecasts + 1)
                LOGGER.info(f'{_LOG_SRC}Price forecast updating')
                state.last_price_forecast = prices
                state.next_price_forecast_check = timestamp + timedelta(minutes=Constants.PRICE_FORECAST_AGE)
            except Exception as err:
                LOGGER.error(f'{_LOG_SRC}Price forecast not available. Error: {err}')

        # A race condition or error may mean that the first forecast is already in the past.
        # Don't bother to update `next_price_forecast_check` as it is no more than 5 minutes in the future.
        while len(prices) > 0 and prices[0].end_time < timestamp:
            LOGGER.info(f'{_LOG_SRC}Price forecast contains old data: {prices[0]}')
            prices = prices[1:]

    return prices[:needed_forecasts]


async def get_consumers_status() -> Dict[str, ConsumerStatus]:
    async with _control_state() as state:
        names = state.consumers.keys()
        statuses = await asyncio.gather(*[
            state.consumers[name].get_status()
            for name in names
        ])
    return {name: status for name, status in zip(names, statuses)}


async def get_connection_status() -> JSONDict:
    async with _control_state() as state:
        result = {
            'controller': state.controller_connection_status,
            'pricer': state.pricer_connection_status,
            'forecaster': state.forecaster_connection_status,
            'database': state.database_connection_status,
        }
        if len(state.consumers) > 0:
            result['consumers'] = state.consumers_connection_status
        return result


async def get_status() -> JSONDict:
    """
    Take a snapshot of the current status.
    """
    control_mode: ControlMode
    power_status: PowerStatus
    price: Price
    consumers_status: Dict[str, ConsumerStatus]

    control_mode, power_status, price, consumers_status = await asyncio.gather(
        get_control_mode(),
        get_power_status(),
        get_price_now(),
        get_consumers_status(),
    )

    result: JSONDict = {
        'control': control_mode.to_json(),
        'power': power_status.to_json(),
        'price': price.to_json(datetime_format=TIMESTAMP_FORMAT, include_time=False),
    }
    if len(consumers_status) > 0:
        result['consumers'] = {
            consumer: status.to_json()
            for consumer, status in consumers_status.items()
        }
        total = sum(json_num(consumer.power) for consumer in consumers_status.values())
        if total > 0:
            house_power = power_status.house_power
            result['consumers_total'] = total
            result['consumers_remaining'] = house_power - total
    return result


async def get_solar_forecast(day: date) -> DailySolarForecast:
    """
    Get the forecast solar power.
    """
    async with _control_state() as state:
        forecaster = state.forecaster
        if forecaster is None:
            LOGGER.error(f'{_LOG_SRC}Solar forecast not available. Error: solar forecaster not connected')
            return _NO_SOLAR_FORECAST

        # Clear stale forecasts
        timestamp = now()
        if state.next_price_forecast_check <= timestamp:
            state.last_solar_forecast.clear()
            state.next_price_forecast_check = timestamp + timedelta(minutes=Constants.SOLAR_FORECAST_AGE)

        key = _DateKey(day.year, day.month, day.day)
        forecast: Optional[DailySolarForecast] = state.last_solar_forecast.get(key)
        if forecast is None:
            try:
                forecast: DailySolarForecast = await forecaster.get_forecast(day)
                LOGGER.info(f'{_LOG_SRC}Updating solar forecast: day = {key}')
                state.last_solar_forecast[key] = forecast
            except Exception as err:
                LOGGER.error(f'{_LOG_SRC}Solar forecast not available. Error: {err}')
                return _NO_SOLAR_FORECAST

    return forecast


@asynccontextmanager
async def solala_database(commit_on_close: bool = True) -> AsyncIterator[SolalaDatabase]:
    async with _control_state() as state:
        database_connections = state.database_connections
        if database_connections is None:
            raise ConnectionError('Database pool not connected')
        database_connections: SolalaDatabaseConnections
        db: SolalaDatabase = await database_connections.get_db()

    # Release the control state lock, then provide the database connection
    yield db

    # Release the database connection
    async with _control_state() as state:
        if database_connections is not state.database_connections:
            raise ConnectionError('Database pool closed with in use')
        await database_connections.put_db(db, commit_on_close)


async def set_control(
        *,
        battery_mode: Optional[BatteryMode] = None,
        inverter_mode: Optional[InverterMode] = None,
        battery_policy: Optional[BatteryPolicy] = None,
        inverter_policy: Optional[InverterPolicy] = None,
        # NEG_FEED_IN_ZERO_EXPORT parameters
        disable_export_price_threshold: Optional[float] = None,
        enable_export_price_threshold: Optional[float] = None,
        # CHEAP_CHARGE parameters
        start_charge_price_threshold: Optional[float] = None,
        stop_charge_price_threshold: Optional[float] = None,
) -> None:
    """
    Set the control loop modes and policies.
    """
    async with _control_state() as state:
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

        await _save_settings()
        LOGGER.info(f'{_LOG_SRC}Control: {json.dumps(state.control_mode.to_json())}')


# =============================================================================
#  Connection management for power control and price
# =============================================================================

async def connect_controller(controller_connection: ControllerConnection) -> None:
    async with _control_state() as state:
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
        state.reset_controller(controller, controller_connection)
        connection_status = controller.get_connection_status()
        LOGGER.info(f'{_LOG_SRC}Power controller connection: {json.dumps(connection_status)}')
        await _save_settings()


async def disconnect_controller() -> None:
    """
    Close the power controller connection.
    """
    async with _control_state() as state:
        if state.controller is not None:
            await state.controller.close()
            state.reset_controller(None, None)
            LOGGER.info(f'{_LOG_SRC}Power controller disconnected')
        await _save_settings()


async def connect_pricer(pricer_connection: PricerConnection) -> None:
    async with _control_state() as state:
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
        state.reset_pricer(pricer, pricer_connection)
        connection_status = pricer.get_connection_status()
        LOGGER.info(f'{_LOG_SRC}Power pricer connection: {json.dumps(connection_status)}')
        await _save_settings()


async def disconnect_pricer() -> None:
    """
    Close the power pricer connection.
    """
    async with _control_state() as state:
        if state.pricer is not None:
            await state.pricer.close()
            state.reset_pricer(None, None)
            LOGGER.info(f'{_LOG_SRC}Pricer disconnected')
        await _save_settings()


async def connect_consumer(name: str, consumer_connection: ConsumerConnection) -> None:
    async with _control_state() as state:
        consumer: PowerConsumer

        if consumer_connection.type == DummyConsumerConnection.TYPE:
            assert isinstance(consumer_connection, DummyConsumerConnection)
            consumer = _connect_dummy_consumer(consumer_connection)
        elif consumer_connection.type == TeslaWallConnectorConnection.TYPE:
            assert isinstance(consumer_connection, TeslaWallConnectorConnection)
            consumer = _connect_tesla_wall_connector(consumer_connection)
        else:
            raise ControlLoopError(
                'unknown consumer connection type',
                errors={'name': name, 'type': consumer_connection.type}
            )

        await disconnect_consumer(name)
        state.reset_consumer(name, consumer, consumer_connection)
        connection_status = consumer.get_connection_status()
        LOGGER.info(f'{_LOG_SRC}Power consumer {name!r} connection: {json.dumps(connection_status)}')
        await _save_settings()


async def disconnect_consumer(name: str) -> None:
    """
    Close a power consumer connection.
    """
    async with _control_state() as state:
        consumer: Optional[PowerConsumer] = state.consumers.get(name)
        if consumer is not None:
            await consumer.close()
            state.reset_consumer(name, None, None)
            LOGGER.info(f'{_LOG_SRC}Power consumer {name!r} disconnected')
        await _save_settings()


async def connect_forecaster(forecaster_connection: ForecasterConnection) -> None:
    async with _control_state() as state:
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
        state.reset_forecaster(forecaster, forecaster_connection)
        connection_status = forecaster.get_connection_status()
        LOGGER.info(f'{_LOG_SRC}Solar forecaster connection: {json.dumps(connection_status)}')
        await _save_settings()


async def disconnect_forecaster() -> None:
    """
    Close the power pricer connection.
    """
    async with _control_state() as state:
        if state.forecaster is not None:
            await state.forecaster.close()
            state.reset_forecaster(None, None)
            LOGGER.info(f'{_LOG_SRC}Solar forecaster disconnected')
        await _save_settings()


async def connect_database(database_connection: DatabaseConnection) -> None:
    async with _control_state() as state:
        database_connections = SolalaDatabaseConnections(
            role=database_connection.role,
            password=database_connection.password,
            host=database_connection.host,
            port=database_connection.port,
            database_name=database_connection.database_name,
        )
        await disconnect_database()
        state.reset_database(database_connections, database_connection)
        connection_status = database_connections.get_connection_status()
        LOGGER.info(f'{_LOG_SRC}Database connection: {json.dumps(connection_status)}')
        await _save_settings()


async def disconnect_database() -> None:
    """
    Close the database connection pool.
    """
    async with _control_state() as state:
        if state.database_connections is not None:
            await state.database_connections.close()
            state.reset_database(None, None)
            LOGGER.info(f'{_LOG_SRC}Database disconnected')
        await _save_settings()


# =============================================================================
#  Support functions
# =============================================================================


async def _database_loop() -> None:
    """
    Execute the database logging loop.
    """
    LOGGER.info(f'{_LOG_SRC}Running database loop')
    while _CONTROL_STATE.control_loop_running:
        iteration_start = now()
        try:
            async with solala_database() as db:
                await _insert_measurement(iteration_start, db)
        except ConnectionError as err:
            LOGGER.error(f'{_LOG_SRC}Database connection error: {err}')

        # Sleep for the remaining time until the next loop iteration.
        iter_time = Constants.DATABASE_LOG_LOOP_TIME
        start_timestamp = (int(iteration_start.timestamp() / iter_time) + 1) * iter_time
        sleeptime: float = start_timestamp - now().timestamp()
        await asyncio.sleep(sleeptime)

    LOGGER.info(f'{_LOG_SRC}Stopped database loop')


async def _insert_measurement(dt_now: datetime, db: SolalaDatabase) -> None:
    LOGGER.info(f'{_LOG_SRC}Gathering a measurement for the database')
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

    forecast: Optional[SolarForecast] = daily_forecast.find_contemporary(dt_now)
    if forecast is None:
        LOGGER.warning(f'{_LOG_SRC}No solar forecast found for {dt_now}')
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
    LOGGER.info(f'{_LOG_SRC}Inserted a measurement into the database')


async def _control_loop() -> None:
    """
    Execute the main control loop.
    """
    LOGGER.info(f'{_LOG_SRC}Running control loop')
    while _CONTROL_STATE.control_loop_running:
        async with _control_state() as state:
            state.iteration_start = now()  # timestamp to calculate loop sleep time
            await _control_step(state)
            listeners = state.listeners.copy()
            state.last_power_valid = False

        # Update the listeners while not holding the control state lock.
        _update_listeners(listeners)

        # Sleep for the remaining time until the next loop iteration.
        # Make adjustment so that iterations tend to fall at whole minutes
        # (assuming `Constants.LOOP_TIME` is a factor of 60).
        # The adjustment is limited to -1 to +1 second away from `Constants.LOOP_TIME`.
        next_start_timestamp = state.iteration_start.timestamp() + Constants.LOOP_TIME
        ideal_start_timestamp = round(next_start_timestamp / Constants.LOOP_TIME) * Constants.LOOP_TIME
        next_start_timestamp += max(-1, min(ideal_start_timestamp - next_start_timestamp, 1))  # limited adjustment
        sleeptime: float = next_start_timestamp - now().timestamp()
        if sleeptime < Constants.LOOP_MIN_SLEEP_TIME:
            LOGGER.warn(f'{_LOG_SRC}Low sleep time: {sleeptime} < {Constants.LOOP_MIN_SLEEP_TIME}')
            sleeptime = Constants.LOOP_MIN_SLEEP_TIME
        await asyncio.sleep(sleeptime)

    LOGGER.info(f'{_LOG_SRC}Stopped control loop')


async def _control_step(state: _ControlState) -> None:
    """
    Perform one functional step of the control loop.
    This function assumes the control state lock is already acquired for `state`.
    No work is performed if the power controller is None.
    No non-manual policies are followed if the power pricer is None.

    Args:
        state: the current control state (with the lock acquired).
    """
    # Check to see if the power controller has changed.
    prev_state = state.prev_state
    if state.controller is None:
        # No work can be done if there is no power controller.
        prev_state.reset(None)
        return
    power_controller: PowerController = state.controller
    if power_controller is not prev_state.controller:
        prev_state.reset(power_controller)

    # Battery Policy - may change Battery Mode
    if state.pricer is not None:
        if state.control_mode.battery_policy == BatteryPolicy.CHEAP_CHARGE:
            price: Price = await get_price_now()
            buy_price = price.buy_price
            if buy_price < state.control_mode.start_charge_price_threshold:
                state.control_mode.battery_mode = BatteryMode.FORCE_CHARGE
            elif buy_price > state.control_mode.enable_export_price_threshold:
                state.control_mode.battery_mode = BatteryMode.ENABLE

    # Battery Mode
    if state.control_mode.battery_mode != prev_state.control_mode.battery_mode:
        match state.control_mode.battery_mode:
            case BatteryMode.ENABLE:
                power_controller.enable_battery()
            case BatteryMode.DISABLE:
                power_controller.disable_battery()
            case BatteryMode.FORCE_CHARGE:
                power_controller.force_charge()
            case BatteryMode.FORCE_DISCHARGE:
                power_controller.force_discharge()
            case BatteryMode.CHARGE_ONLY:
                power_controller.charge_only()
            case BatteryMode.DISCHARGE_ONLY:
                power_controller.discharge_only()

    # Inverter Policy - may change Inverter Mode
    if state.pricer is not None:
        if state.control_mode.inverter_policy == InverterPolicy.NEG_FEED_IN_ZERO_EXPORT:
            price = await get_price_now()
            feed_in_price = price.feed_in_price
            if feed_in_price < state.control_mode.disable_export_price_threshold:
                state.control_mode.inverter_mode = InverterMode.ZERO_EXPORT
            elif feed_in_price > state.control_mode.disable_export_price_threshold:
                state.control_mode.inverter_mode = InverterMode.ENABLE

    # Inverter Mode
    if state.control_mode.inverter_mode != prev_state.control_mode.inverter_mode:
        if state.control_mode.inverter_mode == InverterMode.ENABLE:
            power_controller.enable_inverter()
        # All other cases are managed below as they have a reversion time limit
    # Inverter modes requiring keep-alive pulse
    try:
        match state.control_mode.inverter_mode:
            case InverterMode.DISABLE:
                power_controller.disable_inverter(change_duration=Constants.CONTROL_DURATION)
            case InverterMode.ZERO_EXPORT:
                power_controller.zero_export(change_duration=Constants.CONTROL_DURATION)
    except Exception as e:
        LOGGER.error(f'{_LOG_SRC}Error processing command: {state.control_mode.inverter_mode}. Error: {e}')

    # Remember how we left things
    prev_state.control_mode = copy.copy(state.control_mode)


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
    )


def _connect_dummy_consumer(consumer_connection: DummyConsumerConnection) -> PowerConsumer:
    return DummyPowerConsumer(
        voltage=consumer_connection.voltage,
        current=consumer_connection.current,
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
    addresses: List[_Address] = _resolve_addresses(split_addresses(controller_connection.address))
    if len(addresses) == 0:
        raise ControlLoopError('no controller address provided')

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
        'master': ModbusDevice(master_client, controller_connection.master_device_id),
    }
    slave_names: List[str]
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

    mac_addr_lookup: Dict[str, str] = {
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
        LOGGER.warning(f'{_LOG_SRC}No API token or NMI provided for Amber pricer')
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
    address: _Address = _resolve_addresses([consumer_connection.address])[0]
    try:
        return TeslaWallConnector(address.ip_address, address.mac_address)
    except Exception as err:
        raise ControlLoopError('could not connect Tesla Wall Connector', errors=[str(err)])


def _connect_open_meteo_forecaster(forecaster_connection: OpenMeteoConnection) -> SolarForecaster:
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


def _update_listeners(listeners: Iterable[LoopListener]) -> None:
    """
    Call update on each listener, using the event loop provided by the listener.

    WARNING:
        * The given iterable should not be modified during iteration, i.e.
          this function should be given a copy of the list of listeners.
        * The control state lock should _NOT_ be acquired while calling this function
          as each listener may try to acquire the lock in its own thread.
    """
    for listener in listeners:
        # noinspection PyProtectedMember
        event_loop = listener._event_loop
        asyncio.run_coroutine_threadsafe(listener.update(), event_loop)


def _get_settings(state: _ControlState) -> Settings:
    """
    Take a snapshot of the current settings.
    Assumes the control state lock is held.
    """
    control_mode = state.control_mode
    return Settings(
        controller=state.controller_settings,
        pricer=state.pricer_settings,
        consumers=state.consumers_settings,
        forecaster=state.forecaster_settings,
        database=state.database_settings,

        battery_mode=control_mode.battery_mode,
        inverter_mode=control_mode.inverter_mode,
        battery_policy=control_mode.battery_policy,
        inverter_policy=control_mode.inverter_policy,

        disable_export_price_threshold=control_mode.disable_export_price_threshold,
        enable_export_price_threshold=control_mode.enable_export_price_threshold,

        start_charge_price_threshold=control_mode.start_charge_price_threshold,
        stop_charge_price_threshold=control_mode.stop_charge_price_threshold,
    )


async def _save_settings() -> None:
    """
    This is called when the user settings are changed. We persist the settings
    so that they are available across restarts.
    """
    async with _control_state() as state:
        settings_path = state.settings_path
        if settings_path is not None:
            try:
                with open(settings_path, 'w') as file:
                    settings: Settings = _get_settings(state)
                    print(settings.model_dump_json(), file=file)
            except Exception as e:
                LOGGER.error(f'{_LOG_SRC}Error saving settings: {e}')


async def _load_settings() -> bool:
    """
    Load the persisted settings.

    Returns:
        True if settings were loaded successfully, False otherwise.
    """
    async with _control_state() as state:
        settings_path = state.settings_path
        if settings_path is not None:
            try:
                with open(settings_path, 'r') as file:
                    json_string = file.read()
                settings = Settings.model_validate_json(json_string)
                await configure_from_settings(settings)
                return True
            except Exception as e:
                LOGGER.error(f'{_LOG_SRC}Error loading settings: {e}')
        return False
