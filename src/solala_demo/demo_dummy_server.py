import local_config as config
from solala import server
from solala.control_loop import DummyPricerConnection
from solala.control_loop.settings import Settings, DummyControllerConnection
from solala_demo.log import configure_logger

HOST: str = config.SERVER_IP_ADDRESS
PORT: int = config.SERVER_PORT


def main():
    configure_logger()

    # Optional initial control loop parameters.
    # These will be used if the settings file cannot be loaded or force_settings is True.
    force_settings: bool = True
    settings = Settings(
        controller=DummyControllerConnection(),
        pricer=DummyPricerConnection(
            # buy_price_min=0,
            # buy_price_max=60,
            # feed_in_price_discount_min=2,
            # feed_in_price_discount_max=5,
            # cur_price_is_estimate=False,
        ),
    )

    # DEBUG: Change control loop constants for testing and debugging.
    # Constants.PRICE_LOOK_AHEAD = 0

    server.run_server(
        host=HOST,
        port=PORT,
        settings_path=config.DUMMY_SETTINGS_PATH,
        settings=settings,
        force_settings=force_settings,
    )


if __name__ == '__main__':
    main()
