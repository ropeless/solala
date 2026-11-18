from datetime import time

from solala.constants import Constants
from solala.delegates.power_controller.power_controller import InverterMode
from solala.server import server
from solala.settings import (
    DummyConsumerConnection,
    DummyControllerConnection,
    DummyPricerConnection,
    DummySolarForecasterConnection,
    Settings,
    DummyControllerFailure,
    DummyForecasterFailure,
    DummyPricerFailure,
    DummyConsumerFailure,
    ConsumerConnection,
)
from solala.utils.local_config_help import config
from solala_demo.log import configure_logger


def run_failing_server(
        name: str,
        *,
        controller_failure: DummyControllerFailure | None = None,
        inverter_mode: InverterMode | None = None,
        pricer_failure: DummyPricerFailure | None = None,
        consumer_failure: DummyConsumerFailure | None = None,
        forecaster_failure: DummyForecasterFailure | None = None,
) -> None:
    """
    Run a dummy server with one or more configured failure scenarios.

    Settings are forced so a saved dummy settings file cannot silently
    override the failure being demonstrated.

    Args:
        name: Scenario label displayed in the application title.
        controller_failure: Optional controller failure.
        inverter_mode: Optional initial inverter mode.
        pricer_failure: Optional pricer failure.
        consumer_failure: Optional consumer failure.
        forecaster_failure: Optional solar forecaster failure.
    """
    configure_logger(level=config.APP_LOG_LEVEL)

    consumers: dict[str, ConsumerConnection] = {
        'example_consumer': DummyConsumerConnection(current=5, failure=consumer_failure),
    }
    settings = Settings(
        controller=DummyControllerConnection(failure=controller_failure),
        inverter_mode=inverter_mode,
        pricer=DummyPricerConnection(
            demand_window=(time(15), time(18)),
            failure=pricer_failure,
        ),
        consumers=consumers,
        forecaster=DummySolarForecasterConnection(
            panel_capacity=config.PANEL_CAPACITY,
            inverter_limit=config.INVERTER_LIMIT,
            failure=forecaster_failure,
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
