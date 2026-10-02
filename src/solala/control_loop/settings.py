from typing import Literal, TypeAlias, Optional, Annotated, Union, ClassVar

from pydantic import BaseModel, Field

from solala.control_loop.modes_and_policies import BatteryMode, InverterMode, InverterPolicy, BatteryPolicy

DEFAULT_DISABLE_FEED_IN_PRICE_THRESHOLD: float = -0.1  # disable export below this price
DEFAULT_ENABLE_FEED_IN_PRICE_THRESHOLD: float = 0.1  # re-enable export above this price
DEFAULT_START_CHARGE_PRICE_THRESHOLD: float = 10  # start force charging below this price
DEFAULT_STOP_CHARGE_PRICE_THRESHOLD: float = 11  # stop force charging above this price


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


class TeslaChargerConnection(BaseModel):
    TYPE: ClassVar[Literal['tesla']] = 'tesla'
    type: Literal['tesla'] = 'tesla'

    address: str  # MAC or IP address


ControllerConnection: TypeAlias = Annotated[
    Union[
        ModbusControllerConnection,
        # Add others as needed
    ],
    Field(discriminator='type')
]

PricerConnection: TypeAlias = Annotated[
    Union[
        AmberPricerConnection,
        # Add others as needed
    ],
    Field(discriminator='type')
]

ChargerConnection: TypeAlias = Annotated[
    Union[
        TeslaChargerConnection,
        # Add others as needed
    ],
    Field(discriminator='type')
]


class Settings(BaseModel):
    """
    A class to hold user settings for the application.
    """

    controller: Optional[ControllerConnection] = None
    pricer: Optional[PricerConnection] = None
    charger: Optional[ChargerConnection] = None

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
