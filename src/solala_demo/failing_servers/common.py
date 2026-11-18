from datetime import time

from solala.constants import Constants
from solala.server import server
from solala.settings import (
    DummyConsumerConnection,
    DummyControllerConnection,
    DummyPricerConnection,
    DummySolarForecasterConnection,
    Settings,
    consumers,
)
from solala.utils.local_config_help import config
from solala_demo.log import configure_logger


def run_failing_server(
        name: str,
        *,
        controller: DummyControllerConnection | None = None,
        pricer: DummyPricerConnection | None = None,
        consumer: DummyConsumerConnection | None = None,
        forecaster: DummySolarForecasterConnection | None = None,
) -> None:
    """
    Run a dummy server with one or more configured failure scenarios.

    Settings are forced so a saved dummy settings file cannot silently
    override the failure being demonstrated.

    Args:
        name: Scenario label displayed in the application title.
        controller: Optional controller configuration.
        pricer: Optional pricer configuration.
        consumer: Optional example consumer configuration.
        forecaster: Optional solar forecaster configuration.
    """
    configure_logger(level=config.APP_LOG_LEVEL)

    settings = Settings(
        controller=controller if controller is not None else DummyControllerConnection(),
        pricer=pricer if pricer is not None else DummyPricerConnection(
            demand_window=(time(15), time(18)),
        ),
        consumers=consumers(
            example_consumer=consumer if consumer is not None else DummyConsumerConnection(current=5),
        ),
        forecaster=forecaster if forecaster is not None else DummySolarForecasterConnection(
            panel_capacity=config.PANEL_CAPACITY,
            inverter_limit=config.INVERTER_LIMIT,
        ),
    )

    Constants.APP_NAME += f' ***FAILING DEMO: {name}***'

    server.run_server(
        host=config.SERVER_HOST,
        port=config.SERVER_PORT,
        settings_path=config.DUMMY_SETTINGS_PATH,
        settings=settings,
        force_settings=True,
        database_write=False,
    )
