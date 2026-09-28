import local_config as config
from solala import server
from solala.log import configure_logger
from solala.settings import Settings

HOST: str = config.SERVER_IP_ADDRESS
PORT: int = 80


def main():
    configure_logger()

    # Optional initial control loop parameters.
    settings = Settings(
        modbus_addresses=f'{config.MASTER_INVERTER_ADDR};{config.SLAVE_INVERTER_ADDR}',
        amber_api_token=config.AMBER_API_TOKEN,
        amber_nmi=config.NMI,
        tesla_wall_connector=config.TESLA_WALL_CONNECTOR_ADDR,

        # DEBUG

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

    server.run_server(host=HOST, port=PORT, settings=settings)


if __name__ == '__main__':
    main()
