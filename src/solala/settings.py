from datetime import time
import math
from typing import Annotated, ClassVar, Literal, Self

from pydantic import BaseModel, Field, field_validator, model_validator

from solala.constants import DEFAULT_INVERTER_LIMIT, DEFAULT_INVERTER_EFFICIENCY, DEFAULT_PANEL_TEMPERATURE_COEFFICIENT, \
    DEFAULT_DB_HOST, DEFAULT_DB_PORT, DEFAULT_DB_NAME
from solala.control.modes_and_policies import BatteryMode, InverterMode, InverterPolicy, BatteryPolicy
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
        can_switch: Whether the simulated consumer supports switching.
        include_accumulated_energy: Whether to expose simulated accumulated energy.
    """
    TYPE: ClassVar[Literal['dummy']] = 'dummy'
    type: Literal['dummy'] = 'dummy'

    voltage: float = 240
    current: float = 0
    power: float | None = None
    on: bool = True
    failure: DummyConsumerFailure | None = None
    can_switch: bool = True
    include_accumulated_energy: bool = True


class DummyForecasterFailure(DummyFailure):
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
    failure: DummyForecasterFailure | None = None


class ModbusControllerConnection(BaseModel):
    """
    Configure Modbus power controller.

    Attributes:
        address: Master and optional slave MAC or IP addresses, in that order,
            separated by commas, semicolons, ampersands, or whitespace.
        master_device_id: Modbus device identifier for the master inverter.
        meter_device_id: Modbus device identifier for the meter.
        slave_device_id: Modbus device identifier for the slave inverter.
        power_control_slaves: Whether to apply inverter power curtailment to
            slave inverters as well as the master.
        default_MinRsvPct: Default minimum battery reserve percentage.
        default_WMaxLimPct_RvrtTms: Default inverter control reversion time in seconds.
    """
    TYPE: ClassVar[Literal['modbus']] = 'modbus'
    type: Literal['modbus'] = 'modbus'

    address: str  # The MAC or IP address of the master then slave controllers, separated by commas, semicolons, ampersands, or whitespace.
    master_device_id: int = 1
    meter_device_id: int = 200
    slave_device_id: int = 1
    power_control_slaves: bool = False
    default_MinRsvPct: float = 7
    default_WMaxLimPct_RvrtTms: int = 11


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

    Attributes:
        address: MAC or IP address of the connector.
        cache_duration: Lifetime of each cached API response in seconds.
        timeout: HTTP timeout in seconds.
    """
    TYPE: ClassVar[Literal['tesla']] = 'tesla'
    type: Literal['tesla'] = 'tesla'

    address: str  # MAC or IP address
    cache_duration: float = Field(default=0.1, ge=0, allow_inf_nan=False)
    timeout: float = Field(default=5.0, gt=0, allow_inf_nan=False)


class TuyaCloudConnection(BaseModel):
    """
    Configure Tuya API access and electrical measurement scaling.

    Attributes:
        access_id: Tuya API access identifier.
        access_secret: Tuya API authentication secret.
        device_id: Identifier of the Tuya device.
        voltage_scale_factor: Multiplier applied to reported voltage values.
        current_scale_factor: Multiplier applied to reported current values.
        power_scale_factor: Multiplier applied to reported power values.
        calibration_factor: Multiplier correcting measured current and power.
        cache_duration: How long to cache the device status. Use this to reduce how often the
            API is called. The default value is 300 seconds (5 minutes).
        include_accumulated_energy: Whether to use Tuya's 'add_ele' as accumulated energy in Wh.
        connect_timeout: Seconds to allow for establishing an HTTP connection.
        read_timeout: Seconds to wait for incoming data before timing out.
    """
    TYPE: ClassVar[Literal['tuya_cloud']] = 'tuya_cloud'
    type: Literal['tuya_cloud'] = 'tuya_cloud'

    access_id: str
    access_secret: str
    device_id: str

    voltage_scale_factor: float = 0.1
    current_scale_factor: float = 0.001
    power_scale_factor: float = 0.1
    calibration_factor: float = 1.0
    cache_duration: float = 300
    include_accumulated_energy: bool = False
    connect_timeout: float = Field(default=5.0, gt=0, allow_inf_nan=False)
    read_timeout: float = Field(default=10.0, gt=0, allow_inf_nan=False)

    @field_validator('calibration_factor')
    @classmethod
    def validate_calibration_factor(cls, value: float) -> float:
        if not math.isfinite(value) or value <= 0:
            raise ValueError('calibration_factor must be positive and finite')
        return value


class TuyaLocalConnection(BaseModel):
    """
    Configure a Tuya smart plug accessed directly over the LAN.

    Attributes:
        host: Device IP address or hostname.
        device_id: Tuya device identifier.
        local_key: Local encryption key.
        version: Tuya protocol version.
        calibration_factor: Multiplier correcting measured current and power.
        timeout: Socket timeout in seconds.
        cache_duration: Lifetime of a cached LAN status response in seconds.
    """
    TYPE: ClassVar[Literal['tuya_local']] = 'tuya_local'
    type: Literal['tuya_local'] = 'tuya_local'

    host: str
    device_id: str
    local_key: str
    version: float = 3.5
    calibration_factor: float = 1.0
    timeout: float = 5.0
    cache_duration: float = Field(default=0.1, ge=0, allow_inf_nan=False)

    @field_validator('calibration_factor')
    @classmethod
    def validate_calibration_factor(cls, value: float) -> float:
        if not math.isfinite(value) or value <= 0:
            raise ValueError('calibration_factor must be positive and finite')
        return value


class MatterConnection(BaseModel):
    """
    Configure a Matter power consumer through a Matter Server.

    Attributes:
        host: Matter Server hostname or IP address.
        port: Matter Server WebSocket port.
        node_id: Commissioned Matter node identifier.
        endpoint_id: Endpoint containing the power consumer.
        token: Optional bearer token for server authentication.
        secure: Whether to use a TLS-protected WebSocket.
        timeout: Seconds allowed for WebSocket setup, sending the command, and
            receiving its matching reply after acquiring the request lock.
        cache_duration: How long to reuse node attributes, in seconds.
    """
    TYPE: ClassVar[Literal['matter']] = 'matter'
    type: Literal['matter'] = 'matter'

    host: str
    port: int
    node_id: int
    endpoint_id: int = 1
    token: str | None = None
    secure: bool = False
    timeout: float = 30
    cache_duration: float = Field(default=0.1, ge=0, allow_inf_nan=False)


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
    Configure PostgreSQL connection credentials, server details, and pool sizes.

    Attributes:
        role: Database username.
        password: Database password.
        host: Database server hostname or IP address.
        port: Database server port.
        database_name: Database name.
        min_pool_size: Minimum number of pooled connections.
        max_pool_size: Maximum number of pooled connections.
    """
    role: str
    password: str
    host: str = DEFAULT_DB_HOST
    port: int = DEFAULT_DB_PORT
    database_name: str = DEFAULT_DB_NAME
    min_pool_size: int = Field(default=2, ge=0)
    max_pool_size: int = Field(default=8, gt=0)

    @model_validator(mode='after')
    def _validate_pool_sizes(self) -> Self:
        if self.max_pool_size < self.min_pool_size:
            raise ValueError('max_pool_size must be at least min_pool_size')
        return self


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
    DummyConsumerConnection | TeslaWallConnectorConnection | TuyaCloudConnection | TuyaLocalConnection | MatterConnection,
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
    control the behaviour of the control loop.
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

    # Mode and policy parameters
    fixed_limit_pct: float | None = Field(default=None, ge=0, le=100, allow_inf_nan=False)
    disable_export_price_threshold: float | None = Field(default=None, allow_inf_nan=False)
    enable_export_price_threshold: float | None = Field(default=None, allow_inf_nan=False)
    start_charge_price_threshold: float | None = Field(default=None, allow_inf_nan=False)
    stop_charge_price_threshold: float | None = Field(default=None, allow_inf_nan=False)
