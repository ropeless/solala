from typing import Literal, TypeAlias, Optional, Annotated, Union, ClassVar, Dict

from pydantic import BaseModel, Field

from solala.control_loop.modes_and_policies import BatteryMode, InverterMode, InverterPolicy, BatteryPolicy

DEFAULT_DISABLE_FEED_IN_PRICE_THRESHOLD: float = -0.1  # disable export below this price
DEFAULT_ENABLE_FEED_IN_PRICE_THRESHOLD: float = 0.1  # re-enable export above this price
DEFAULT_START_CHARGE_PRICE_THRESHOLD: float = 10  # start force charging below this price
DEFAULT_STOP_CHARGE_PRICE_THRESHOLD: float = 11  # stop force charging above this price

DEFAULT_INVERTER_EFFICIENCY: float = 0.96  # as a fraction (0 to 1)
DEFAULT_INVERTER_LIMIT: float = float('inf')  # in Watts
DEFAULT_TEMPERATURE_COEFFICIENT: float = -0.004  # in Celsius


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
    inverter_limit: float = DEFAULT_INVERTER_LIMIT
    inverter_efficiency: float = DEFAULT_INVERTER_EFFICIENCY
    temperature_coefficient: float = DEFAULT_TEMPERATURE_COEFFICIENT


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
