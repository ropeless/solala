from datetime import time
from typing import Annotated, ClassVar, Literal

from pydantic import BaseModel, Field

from solala.constants import DEFAULT_INVERTER_LIMIT, DEFAULT_INVERTER_EFFICIENCY, DEFAULT_PANEL_TEMPERATURE_COEFFICIENT, \
    DEFAULT_DB_HOST, DEFAULT_DB_PORT, DEFAULT_DB_NAME
from solala.control_loop.modes_and_policies import BatteryMode, InverterMode, InverterPolicy, BatteryPolicy


class DummyControllerConnection(BaseModel):
    TYPE: ClassVar[Literal['dummy']] = 'dummy'
    type: Literal['dummy'] = 'dummy'

    inverter_limit: float = 8000
    house_power: float = 3000
    max_charge_param: float = 3000
    max_discharge_param: float = 3000


class DummyPricerConnection(BaseModel):
    TYPE: ClassVar[Literal['dummy']] = 'dummy'
    type: Literal['dummy'] = 'dummy'

    buy_price_min: float = 1
    buy_price_max: float = 20
    feed_in_price_discount_min: float = 2
    feed_in_price_discount_max: float = 5
    cur_price_is_estimate: bool = False
    demand_window: tuple[time, time] | None = None


class DummyConsumerConnection(BaseModel):
    TYPE: ClassVar[Literal['dummy']] = 'dummy'
    type: Literal['dummy'] = 'dummy'

    voltage: float = 240
    current: float = 0


class DummySolarForecasterConnection(BaseModel):
    TYPE: ClassVar[Literal['dummy']] = 'dummy'
    type: Literal['dummy'] = 'dummy'

    panel_capacity: float = 9000
    inverter_limit: float = 8000


class ModbusControllerConnection(BaseModel):
    TYPE: ClassVar[Literal['modbus']] = 'modbus'
    type: Literal['modbus'] = 'modbus'

    address: str  # The MAC or IP address of the master then slave controllers, separated by commas, semicolons, ampersands, or whitespace.
    master_device_id: int = 1
    meter_device_id: int = 200
    slave_device_id: int = 1


class AmberPricerConnection(BaseModel):
    TYPE: ClassVar[Literal['amber']] = 'amber'
    type: Literal['amber'] = 'amber'

    api_token: str
    nmi: str


class TeslaWallConnectorConnection(BaseModel):
    TYPE: ClassVar[Literal['tesla']] = 'tesla'
    type: Literal['tesla'] = 'tesla'

    address: str  # MAC or IP address


class TuyaConnection(BaseModel):
    TYPE: ClassVar[Literal['tuya']] = 'tuya'
    type: Literal['tuya'] = 'tuya'

    access_id: str
    access_secret: str
    device_id: str


class OpenMeteoConnection(BaseModel):
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
    A class to hold user settings for the control loop.
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


def consumers(**kwargs: ConsumerConnection) -> dict[str, ConsumerConnection]:
    """
    Helper to keep type inference tidy.
    """
    return kwargs
