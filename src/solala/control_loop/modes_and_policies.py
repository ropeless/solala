from enum import Enum, auto


class BatteryMode(Enum):
    UNKNOWN = auto()  # The battery has not been configured by the control loop yet
    ENABLE = auto()  # The battery is configured for normal operation, charge and discharge
    DISABLE = auto()  # The battery is logically disconnected, no charge or discharge
    FORCE_CHARGE = auto()  # The battery is configured to force charge to its maximum charge
    FORCE_DISCHARGE = auto()  # The battery is configured to force discharge to its minimum charge


class InverterMode(Enum):
    UNKNOWN = auto()  # The inverter has not been configured by the control loop yet
    ENABLE = auto()  # The inverter is configured for normal operation for grid import and export
    DISABLE = auto()  # The inverter is configured to not produce power
    ZERO_EXPORT = auto()  # The inverter is controlled to minimise export to the grid


class BatteryPolicy(Enum):
    MANUAL = auto()
    CHEAP_CHARGE = auto()  # set battery mode to FORCE_CHARGE if power buy price is low


class InverterPolicy(Enum):
    MANUAL = auto()
    NEG_FEED_IN_ZERO_EXPORT = auto()  # set inverter mode to ZERO_EXPORT if feed-in price is negative
