import local_config as config
from solala import server
from solala.control_loop.history_file import HistoryFile
from solala.control_loop.settings import Settings, ModbusControllerConnection, AmberPricerConnection, \
    TeslaWallConnectorConnection
from solala.server_constants import LOGGER
from solala_demo.log import configure_logger

HOST: str = config.SERVER_IP_ADDRESS
PORT: int = config.SERVER_PORT


def main():
    configure_logger()

    # Optional initial control loop parameters.
    # These will be used if the settings file cannot be loaded or force_settings is True.
    force_settings: bool = False
    settings = Settings(

        controller=ModbusControllerConnection(address=f'{config.MASTER_INVERTER_ADDR};{config.SLAVE_INVERTER_ADDR}'),
        pricer=AmberPricerConnection(api_token=config.AMBER_API_TOKEN, nmi=config.NMI),
        consumers={'car_charger': TeslaWallConnectorConnection(address=config.TESLA_WALL_CONNECTOR_ADDR)},

        # inverter_mode=InverterMode.ENABLE,
        # inverter_policy=InverterPolicy.NEG_FEED_IN_ZERO_EXPORT,
        # disable_export_price_threshold=10,
        # enable_export_price_threshold=20,
        # battery_mode=BatteryMode.DISABLE,

        # battery_mode=BatteryMode.ENABLE,
        # battery_policy=BatteryPolicy.CHEAP_CHARGE,
        # start_charge_price_threshold = 1,
        # stop_charge_price_threshold = 2,
    )

    # DEBUG: Change control loop constants for testing and debugging.
    # Constants.PRICE_LOOK_AHEAD = 0

    # Create and register a history file
    history = HistoryFile(config.HISTORY_FILE)
    LOGGER.info(f'registered history file: {history}')

    server.run_server(
        host=HOST,
        port=PORT,
        settings_path=config.SETTINGS_PATH,
        settings=settings,
        force_settings=force_settings,
    )


if __name__ == '__main__':
    main()
