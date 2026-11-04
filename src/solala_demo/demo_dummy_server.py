import local_config as config
from solala.constants import Constants
from solala.server import server
from solala.settings import Settings, DummyControllerConnection, DummyPricerConnection, \
    DummyConsumerConnection, DummySolarForecasterConnection
from solala_demo.log import configure_logger


def main():
    configure_logger()

    # Optional initial control loop parameters.
    # These will be used if the settings file cannot be loaded or force_settings is True.
    force_settings: bool = True
    settings = Settings(
        controller=DummyControllerConnection(),
        pricer=DummyPricerConnection(),
        consumers={'example_consumer': DummyConsumerConnection(current=5)},
        forecaster=DummySolarForecasterConnection(
            panel_capacity=config.PANEL_CAPACITY,
            inverter_limit=config.INVERTER_LIMIT,
        ),

    )

    Constants.APP_NAME += ' ***DUMMY SERVER***'

    server.run_server(
        host=config.SERVER_HOST,
        port=config.SERVER_PORT,
        settings_path=config.DUMMY_SETTINGS_PATH,
        settings=settings,
        force_settings=config.FORCE_SETTINGS,
    )


if __name__ == '__main__':
    main()
