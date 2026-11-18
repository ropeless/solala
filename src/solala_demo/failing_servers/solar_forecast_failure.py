from solala.delegates.solar_forecaster.dummy_solar_forecaster.dummy_solar_forecaster import (
    FailureLocation,
)
from solala.settings import DummyForecasterFailure
from solala_demo.failing_servers._common import run_failing_server


def main() -> None:
    """
    Demonstrate a persistent solar forecast timeout in the UI.
    """
    run_failing_server(
        'solar forecast timeout',
        forecaster_failure=DummyForecasterFailure(
            location=FailureLocation.get_forecast,
            exception=TimeoutError('Simulated solar forecast timeout'),
        ),
    )


if __name__ == '__main__':
    main()
