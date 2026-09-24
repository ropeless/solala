from dataclasses import dataclass

from solala.control_loop import BatteryMode, InverterMode, InverterPolicy, DEFAULT_DISABLE_FEED_IN_PRICE_THRESHOLD, \
    DEFAULT_ENABLE_FEED_IN_PRICE_THRESHOLD, BatteryPolicy, DEFAULT_START_CHARGE_PRICE_THRESHOLD, \
    DEFAULT_STOP_CHARGE_PRICE_THRESHOLD


@dataclass
class Settings:
    """
    A class to hold user settings for the application.

    Lists of addresses can be separated by commas, semicolons, ampersands, or whitespace.
    """

    power_controller_addresses: str = ''  # The MAC or IP address of the master then slave controllers

    power_pricer_api_token: str = ''
    power_pricer_nmi: str = ''

    battery_mode: BatteryMode = BatteryMode.UNKNOWN
    inverter_mode: InverterMode = InverterMode.UNKNOWN
    battery_policy: BatteryPolicy = BatteryPolicy.MANUAL
    inverter_policy: InverterPolicy = InverterPolicy.MANUAL

    # NEG_FEED_IN_ZERO_EXPORT parameters
    disable_export_price_threshold: float = DEFAULT_DISABLE_FEED_IN_PRICE_THRESHOLD
    enable_export_price_threshold: float = DEFAULT_ENABLE_FEED_IN_PRICE_THRESHOLD

    # CHEAP_CHARGE parameters
    start_charge_price_threshold: float = DEFAULT_START_CHARGE_PRICE_THRESHOLD
    stop_charge_price_threshold: float = DEFAULT_STOP_CHARGE_PRICE_THRESHOLD
