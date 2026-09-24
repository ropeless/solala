from local_config import MASTER_INVERTER_MAC_ADDR, SLAVE_INVERTER_MAC_ADDR, AMBER_API_TOKEN, NMI
from solala import server
from solala.log import configure_logger
from solala.settings import Settings
from solala.utils.network import get_local_ip

HOST = get_local_ip()
PORT = 80


def main():
    configure_logger()

    # Optional initial control loop parameters.
    settings = Settings(
        power_controller_addresses=f'{MASTER_INVERTER_MAC_ADDR};{SLAVE_INVERTER_MAC_ADDR}',
        power_pricer_api_token=AMBER_API_TOKEN,
        power_pricer_nmi=NMI,

        # DEBUG

        # export_mode=ExportMode.ENABLE,
        # export_policy=ExportPolicy.NEG_FEED_IN_DISABLE,
        # disable_export_price_threshold=100,
        # enable_export_price_threshold=200,
        # battery_mode=BatteryMode.DISABLE,

        # battery_mode=BatteryMode.ENABLE,
        # battery_policy=BatteryPolicy.CHEAP_CHARGE,
        # start_charge_price_threshold = 1,
        # stop_charge_price_threshold = 2,
    )

    server.run_server(host=HOST, port=PORT, settings=settings)


if __name__ == '__main__':
    main()
