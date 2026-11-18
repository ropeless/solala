from solala.delegates.solar_forecaster.dummy_solar_forecaster.dummy_solar_forecaster import (
    FailureLocation,
)
from solala.settings import DummySolarFailure, DummySolarForecasterConnection
from solala.utils.local_config_help import config
from solala_demo.failing_servers.common import run_failing_server


def main() -> None:
    """
    Demonstrate intermittent solar forecast failures and recovery.
    """
    run_failing_server(
        'intermittent solar forecast',
        forecaster=DummySolarForecasterConnection(
            panel_capacity=config.PANEL_CAPACITY,
            inverter_limit=config.INVERTER_LIMIT,
            failure=DummySolarFailure(
                location=FailureLocation.get_forecast,
                probability=0.5,
                exception=TimeoutError('Simulated intermittent solar forecast timeout'),
            ),
        ),
    )


if __name__ == '__main__':
    main()
