from datetime import time
from typing import Annotated, ClassVar, Literal

from pydantic import BaseModel, Field

from solala.constants import DEFAULT_INVERTER_LIMIT, DEFAULT_INVERTER_EFFICIENCY, DEFAULT_PANEL_TEMPERATURE_COEFFICIENT, \
    DEFAULT_DB_HOST, DEFAULT_DB_PORT, DEFAULT_DB_NAME
from solala.control_loop.modes_and_policies import BatteryMode, InverterMode, InverterPolicy, BatteryPolicy
from solala.delegates.solar_forecaster.dummy_solar_forecaster import dummy_solar_forecaster
from solala.delegates.power_consumer.dummy_power_consumer import dummy_power_consumer
from solala.delegates.power_pricer.dummy_power_pricer import dummy_power_pricer
from solala.delegates.power_controller.dummy_power_controller import dummy_power_controller
from solala.utils.dummy_failure import DummyFailure


class DummyControllerFailure(DummyFailure):
    """
    Restrict simulated controller failures to supported operations.
    """

    location: dummy_power_controller.FailureLocation


class DummyControllerConnection(BaseModel):
    """
    Configure a simulated power controller and its power limits.

    Attributes:
        inverter_limit: Maximum simulated inverter output in watts.
        house_power: Simulated household power consumption in watts.
        max_charge_param: Maximum battery charging power in watts.
        max_discharge_param: Maximum battery discharging power in watts.
        failure: Optional simulated failure configuration.
    """
    TYPE: ClassVar[Literal['dummy']] = 'dummy'
    type: Literal['dummy'] = 'dummy'

    inverter_limit: float = 8000
    house_power: float = 3000
    max_charge_param: float = 3000
    max_discharge_param: float = 3000
    failure: DummyControllerFailure | None = None


class DummyPricerFailure(DummyFailure):
    """
    Restrict simulated price failures to supported operations.
    """

    location: dummy_power_pricer.FailureLocation


class DummyPricerConnection(BaseModel):
    """
    Configure a simulated electricity pricer and an optional demand window.

    Attributes:
        buy_price_min: Lower bound for simulated electricity purchase prices.
        buy_price_max: Upper bound for simulated electricity purchase prices.
        feed_in_price_discount_min: Lower bound for the simulated feed-in price discount.
        feed_in_price_discount_max: Upper bound for the simulated feed-in price discount.
        cur_price_is_estimate: Whether the current simulated price is marked as estimated.
        demand_window: Optional start and end times of a demand window.
        failure: Optional simulated failure configuration.
    """
    TYPE: ClassVar[Literal['dummy']] = 'dummy'
    type: Literal['dummy'] = 'dummy'

    buy_price_min: float = 1
    buy_price_max: float = 20
    feed_in_price_discount_min: float = 2
    feed_in_price_discount_max: float = 5
    cur_price_is_estimate: bool = False
    demand_window: tuple[time, time] | None = None
    failure: DummyPricerFailure | None = None


class DummyConsumerFailure(DummyFailure):
    """
    Restrict simulated consumer failures to supported operations.
    """

    location: dummy_power_consumer.FailureLocation


class DummyConsumerConnection(BaseModel):
    """
    Configure a simulated power consumer.

    Attributes:
        voltage: Simulated supply voltage in volts.
        current: Simulated current in amperes.
        power: Active power in watts. Defaults to voltage multiplied by
                current when omitted. If not None, then must be <= voltage * current.
        on: Is the device switched on. Defaults to True.
        failure: Optional simulated failure configuration.
    """
    TYPE: ClassVar[Literal['dummy']] = 'dummy'
    type: Literal['dummy'] = 'dummy'

    voltage: float = 240
    current: float = 0
    power: float | None = None
    on: bool = True
    failure: DummyConsumerFailure | None = None


class DummySolarFailure(DummyFailure):
    """
    Restrict solar forecast fault injection to supported operations.
    """
    location: dummy_solar_forecaster.FailureLocation


class DummySolarForecasterConnection(BaseModel):
    """
    Configure a simulated solar forecaster.

    Attributes:
        panel_capacity: Rated solar panel capacity in watts.
        inverter_limit: Maximum inverter output in watts.
        failure: Optional configured simulated failure.
    """
    TYPE: ClassVar[Literal['dummy']] = 'dummy'
    type: Literal['dummy'] = 'dummy'

    panel_capacity: float = 9000
    inverter_limit: float = 8000
    failure: DummySolarFailure | None = None


class ModbusControllerConnection(BaseModel):
    """
    Configure Modbus power controller.

    Attributes:
        address: Master and optional slave MAC or IP addresses, in that order,
            separated by commas, semicolons, ampersands, or whitespace.
        master_device_id: Modbus device identifier for the master inverter.
        meter_device_id: Modbus device identifier for the meter.
        slave_device_id: Modbus device identifier for the slave inverter.
    """
    TYPE: ClassVar[Literal['modbus']] = 'modbus'
    type: Literal['modbus'] = 'modbus'

    address: str  # The MAC or IP address of the master then slave controllers, separated by commas, semicolons, ampersands, or whitespace.
    master_device_id: int = 1
    meter_device_id: int = 200
    slave_device_id: int = 1


class AmberPricerConnection(BaseModel):
    """
    Configure Amber electricity pricing API access.

    Attributes:
        api_token: Amber API authentication token.
        nmi: National Metering Identifier for the electricity connection.
    """
    TYPE: ClassVar[Literal['amber']] = 'amber'
    type: Literal['amber'] = 'amber'

    api_token: str
    nmi: str


class TeslaWallConnectorConnection(BaseModel):
    """
    Configure a Tesla Wall Connector using its MAC or IP address.
    """
    TYPE: ClassVar[Literal['tesla']] = 'tesla'
    type: Literal['tesla'] = 'tesla'

    address: str  # MAC or IP address


class TuyaConnection(BaseModel):
    """
    Configure Tuya API access and electrical measurement scaling.

    Attributes:
        access_id: Tuya API access identifier.
        access_secret: Tuya API authentication secret.
        device_id: Identifier of the Tuya device.
        voltage_scale_factor: Multiplier applied to reported voltage values.
        current_scale_factor: Multiplier applied to reported current values.
        power_scale_factor: Multiplier applied to reported power values.
        cache_duration: How long to cache the device status. Use this to reduce how often the
                API is called. The default value is 300 seconds (5 minutes).

    """
    TYPE: ClassVar[Literal['tuya']] = 'tuya'
    type: Literal['tuya'] = 'tuya'

    access_id: str
    access_secret: str
    device_id: str

    voltage_scale_factor: float = 0.1
    current_scale_factor: float = 0.001
    power_scale_factor: float = 0.1
    cache_duration: float = 300


class OpenMeteoConnection(BaseModel):
    """
    Configure the Open-Meteo solar forecast and photovoltaic system model.

    Attributes:
        latitude: Site latitude in degrees.
        longitude: Site longitude in degrees.
        panel_orientation: Panel azimuth in degrees.
        panel_tilt: Panel inclination in degrees.
        panel_capacity: Rated photovoltaic panel capacity in watts.
        panel_temperature_coefficient: Panel power temperature coefficient.
        inverter_limit: Maximum inverter output in watts.
        inverter_efficiency: Inverter conversion efficiency as a fraction.
    """
    TYPE: ClassVar[Literal['open_meteo']] = 'open_meteo'
    type: Literal['open_meteo'] = 'open_meteo'

    latitude: float
    longitude: float
    panel_orientation: float
    panel_tilt: float
    panel_capacity: float
    panel_temperature_coefficient: float = DEFAULT_PANEL_TEMPERATURE_COEFFICIENT
    inverter_limit: float = DEFAULT_INVERTER_LIMIT
    inverter_efficiency: float = DEFAULT_INVERTER_EFFICIENCY


class DatabaseConnection(BaseModel):
    """
    Configure PostgreSQL connection credentials and server details.
    """
    role: str
    password: str
    host: str = DEFAULT_DB_HOST
    port: int = DEFAULT_DB_PORT
    database_name: str = DEFAULT_DB_NAME


# =====================================================================================
#  Generic connection types
# =====================================================================================

type ControllerConnection = Annotated[
    DummyControllerConnection | ModbusControllerConnection,
    Field(discriminator='type')
]

type PricerConnection = Annotated[
    DummyPricerConnection | AmberPricerConnection,
    Field(discriminator='type')
]

type ConsumerConnection = Annotated[
    DummyConsumerConnection | TeslaWallConnectorConnection | TuyaConnection,
    Field(discriminator='type')
]

type ForecasterConnection = Annotated[
    DummySolarForecasterConnection | OpenMeteoConnection,
    Field(discriminator='type')
]


class Settings(BaseModel):
    """
    Hold delegate connections, operating modes, policies, and control settings.

    Optional connection fields identify configured services. Policy thresholds
    and register logging settings control the behaviour of the control loop.
    """

    controller: ControllerConnection | None = None
    pricer: PricerConnection | None = None
    forecaster: ForecasterConnection | None = None
    consumers: dict[str, ConsumerConnection] | None = None
    database: DatabaseConnection | None = None

    battery_mode: BatteryMode | None = None
    inverter_mode: InverterMode | None = None
    battery_policy: BatteryPolicy | None = None
    inverter_policy: InverterPolicy | None = None

    # NEG_FEED_IN_ZERO_EXPORT parameters
    disable_export_price_threshold: float | None = None
    enable_export_price_threshold: float | None = None

    # CHEAP_CHARGE parameters
    start_charge_price_threshold: float | None = None
    stop_charge_price_threshold: float | None = None

    registers_to_log: str | None = None
