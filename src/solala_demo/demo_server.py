from solala.constants import Constants
from solala.server import server
from solala.settings import Settings, ModbusControllerConnection, AmberPricerConnection, \
    TeslaWallConnectorConnection, OpenMeteoConnection, DatabaseConnection, TuyaConnection, TuyaLocalConnection, \
    MatterConnection, ConsumerConnection
from solala.utils.local_config_help import config
from solala_demo.log import configure_logger


def main() -> None:
    configure_logger(level=config.APP_LOG_LEVEL)

    settings = Settings(
        controller=ModbusControllerConnection(address=f'{config.MASTER_INVERTER_ADDR};{config.SLAVE_INVERTER_ADDR}'),
        pricer=AmberPricerConnection(api_token=config.AMBER_API_TOKEN, nmi=config.NMI),
        consumers=configure_demo_consumers(),
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
        solala_storage_secret=config.SOLALA_STORAGE_SECRET,
    )


def configure_demo_consumers() -> dict[str, ConsumerConnection]:
    consumers: dict[str, ConsumerConnection] = {}

    # Tesla Wall Connector (tesla_charger)
    tesla_charger: str | None = config.get('TESLA_WALL_CONNECTOR_ADDR')
    if tesla_charger:
        consumers['tesla_charger'] = TeslaWallConnectorConnection(address=config.TESLA_WALL_CONNECTOR_ADDR)
    outlet_charger: str | None = config.get('POWER_POINT_DEVICE')

    # TuyaConnection via cloud (outlet_charger_cloud)
    if outlet_charger:
        consumers['outlet_charger_cloud'] = TuyaConnection(
            device_id=outlet_charger,
            access_id=config.POWER_POINT_ACCESS_ID,
            access_secret=config.POWER_POINT_ACCESS_SECRET,
        )
    local_outlet: str | None = config.get('TUYA_LOCAL_HOST')

    # Tuya connection via LAN (outlet_charger_local)
    if local_outlet:
        consumers['outlet_charger_local'] = TuyaLocalConnection(
            host=local_outlet,
            device_id=config.TUYA_LOCAL_DEVICE_ID,
            local_key=config.TUYA_LOCAL_KEY,
            version=float(config.get('TUYA_LOCAL_VERSION', 3.5)),
            calibration_factor=0.8,
        )

    # Devices known to the Matter server.
    matter_device_ids: dict[int, str] = config.get('MATTER_DEVICE_IDS', {})
    for node_id, name in matter_device_ids.items():
        consumers[name] = MatterConnection(
            host=config.MATTER_SERVER_HOST,
            port=config.MATTER_SERVER_PORT,
            node_id=node_id,
        )

    return consumers


if __name__ == '__main__':
    main()
