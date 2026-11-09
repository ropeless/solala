from datetime import time
from typing import Literal, TypeAlias, Optional, Annotated, Union, ClassVar, Dict, Tuple

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
    demand_window: Optional[Tuple[time, time]] = None


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

ControllerConnection: TypeAlias = Annotated[
    Union[
        DummyControllerConnection,
        ModbusControllerConnection,
        # Add others as needed
    ],
    Field(discriminator='type')
]

PricerConnection: TypeAlias = Annotated[
    Union[
        DummyPricerConnection,
        AmberPricerConnection,
        # Add others as needed
    ],
    Field(discriminator='type')
]

ConsumerConnection: TypeAlias = Annotated[
    Union[
        DummyConsumerConnection,
        TeslaWallConnectorConnection,
        # Add others as needed
    ],
    Field(discriminator='type')
]

ForecasterConnection: TypeAlias = Annotated[
    Union[
        DummySolarForecasterConnection,
        OpenMeteoConnection,
        # Add others as needed
    ],
    Field(discriminator='type')
]


class Settings(BaseModel):
    """
    A class to hold user settings for the control loop.
    """

    controller: Optional[ControllerConnection] = None
    pricer: Optional[PricerConnection] = None
    forecaster: Optional[ForecasterConnection] = None
    consumers: Optional[Dict[str, ConsumerConnection]] = None
    database: Optional[DatabaseConnection] = None

    battery_mode: Optional[BatteryMode] = None
    inverter_mode: Optional[InverterMode] = None
    battery_policy: Optional[BatteryPolicy] = None
    inverter_policy: Optional[InverterPolicy] = None

    # NEG_FEED_IN_ZERO_EXPORT parameters
    disable_export_price_threshold: Optional[float] = None
    enable_export_price_threshold: Optional[float] = None

    # CHEAP_CHARGE parameters
    start_charge_price_threshold: Optional[float] = None
    stop_charge_price_threshold: Optional[float] = None

    registers_to_log: Optional[str] = None


def consumers(**kwargs: ConsumerConnection) -> Dict[str, ConsumerConnection]:
    """
    Helper to keep type inference tidy.
    """
    return kwargs
