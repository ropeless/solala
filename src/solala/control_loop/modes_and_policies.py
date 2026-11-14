from dataclasses import dataclass
from enum import Enum, auto

from solala.constants import DEFAULT_DISABLE_FEED_IN_PRICE_THRESHOLD, DEFAULT_ENABLE_FEED_IN_PRICE_THRESHOLD, \
    DEFAULT_START_CHARGE_PRICE_THRESHOLD, DEFAULT_STOP_CHARGE_PRICE_THRESHOLD
from solala.utils.json_extras import JSONDict


class BatteryMode(Enum):
    """
    Operating modes requested for the battery.
    """
    UNKNOWN = auto()  # The battery has not been configured by the control loop yet
    ENABLE = auto()  # The battery is configured for normal operation, charge and discharge
    DISABLE = auto()  # The battery is logically disconnected, no charge or discharge
    FORCE_CHARGE = auto()  # The battery is configured to force charge to its maximum charge
    FORCE_DISCHARGE = auto()  # The battery is configured to force discharge to its minimum charge
    CHARGE_ONLY = auto()  # Allow the battery to charge but not discharge
    DISCHARGE_ONLY = auto()  # Allow the battery to discharge but not charge


class InverterMode(Enum):
    """
    Operating modes requested for the inverter.
    """
    UNKNOWN = auto()  # The inverter has not been configured by the control loop yet
    ENABLE = auto()  # The inverter is configured for normal operation for grid import and export
    DISABLE = auto()  # The inverter is configured to not produce power
    ZERO_EXPORT = auto()  # The inverter is controlled to minimise export to the grid


class BatteryPolicy(Enum):
    """
    Policies for selecting the battery mode automatically or manually.
    """
    MANUAL = auto()
    CHEAP_CHARGE = auto()  # set battery mode to FORCE_CHARGE if power buy price is low


class InverterPolicy(Enum):
    """
    Policies for selecting the inverter mode automatically or manually.
    """
    MANUAL = auto()
    NEG_FEED_IN_ZERO_EXPORT = auto()  # set inverter mode to ZERO_EXPORT if feed-in price is negative


@dataclass
class ControlMode:
    """
    Specify the operating modes, policies, and price thresholds requested by the user.

    Attributes:
        battery_mode: Requested battery operating mode.
        inverter_mode: Requested inverter operating mode.
        battery_policy: Policy governing automatic battery mode selection.
        inverter_policy: Policy governing automatic inverter mode selection.
        disable_export_price_threshold: Feed-in price below which export is disabled.
        enable_export_price_threshold: Feed-in price above which export is re-enabled.
        start_charge_price_threshold: Buy price below which forced charging starts.
        stop_charge_price_threshold: Buy price above which forced charging stops.
    """
    battery_mode: BatteryMode = BatteryMode.UNKNOWN
    inverter_mode: InverterMode = InverterMode.UNKNOWN
    battery_policy: BatteryPolicy = BatteryPolicy.MANUAL
    inverter_policy: InverterPolicy = InverterPolicy.MANUAL

    # Control mode policy parameters
    disable_export_price_threshold: float = DEFAULT_DISABLE_FEED_IN_PRICE_THRESHOLD
    enable_export_price_threshold: float = DEFAULT_ENABLE_FEED_IN_PRICE_THRESHOLD
    start_charge_price_threshold: float = DEFAULT_START_CHARGE_PRICE_THRESHOLD
    stop_charge_price_threshold: float = DEFAULT_STOP_CHARGE_PRICE_THRESHOLD

    def to_json(self) -> JSONDict:
        """
        Convert the control settings to a JSON-compatible dictionary.

        Returns:
            A dictionary containing separate battery and inverter settings,
            with modes and policies represented by their enum names.
        """
        battery: JSONDict = {
            'mode': self.battery_mode.name,
            'policy': self.battery_policy.name,
            'start_charge_price_threshold': self.start_charge_price_threshold,
            'stop_charge_price_threshold': self.stop_charge_price_threshold,
        }
        inverter: JSONDict = {
            'mode': self.inverter_mode.name,
            'policy': self.inverter_policy.name,
            'disable_export_price_threshold': self.disable_export_price_threshold,
            'enable_export_price_threshold': self.enable_export_price_threshold,
        }
        return {
            'battery': battery,
            'inverter': inverter,
        }
