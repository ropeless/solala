from solala.utils.local_config_help import config
from solala.constants import Constants
from solala.server import server
from solala.settings import Settings, ModbusControllerConnection, AmberPricerConnection, \
    TeslaWallConnectorConnection, OpenMeteoConnection, DatabaseConnection, consumers, TuyaConnection
from solala_demo.log import configure_logger


def main():
    configure_logger(level=config.APP_LOG_LEVEL)

    # Optional initial control loop parameters.
    # These will be used if the settings file cannot be loaded or force_settings is True.
    settings = Settings(

        controller=ModbusControllerConnection(address=f'{config.MASTER_INVERTER_ADDR};{config.SLAVE_INVERTER_ADDR}'),
        pricer=AmberPricerConnection(api_token=config.AMBER_API_TOKEN, nmi=config.NMI),
        consumers=consumers(
            tesla_charger=TeslaWallConnectorConnection(address=config.TESLA_WALL_CONNECTOR_ADDR),
            outlet_charger=TuyaConnection(
                access_id=config.POWER_POINT_ACCESS_ID,
                access_secret=config.POWER_POINT_ACCESS_SECRET,
                device_id=config.POWER_POINT_DEVICE,
            ),
        ),

        forecaster=OpenMeteoConnection(
            latitude=config.LATITUDE,
            longitude=config.LONGITUDE,
            panel_orientation=config.PANEL_ORIENTATION,
            panel_tilt=config.PANEL_TILT,
            panel_capacity=config.PANEL_CAPACITY,
            panel_temperature_coefficient=config.PANEL_TEMPERATURE_COEFFICIENT,
            inverter_limit=config.INVERTER_LIMIT,
            inverter_efficiency=config.INVERTER_EFFICIENCY,
        ),

        database=DatabaseConnection(
            role=config.DATABASE_APP_ROLE,
            password=config.DATABASE_APP_PASSWORD,
            host=config.DATABASE_HOST,
            port=config.DATABASE_PORT,
            database_name=config.DATABASE_NAME,
        ),

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

    Constants.APP_NAME += config.APP_NAME_POSTFIX

    server.run_server(
        host=config.SERVER_HOST,
        port=config.SERVER_PORT,
        settings_path=config.SETTINGS_PATH,
        settings=settings,
        force_settings=config.FORCE_SETTINGS,
        database_write=config.DATABASE_WRITE,
    )


if __name__ == '__main__':
    main()
