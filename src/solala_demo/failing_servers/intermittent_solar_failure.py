from datetime import timedelta

from solala.constants import Constants
from solala.delegates.solar_forecaster.dummy_solar_forecaster.dummy_solar_forecaster import (
    FailureLocation,
)
from solala.settings import DummyForecasterFailure
from solala_demo.failing_servers._common import run_failing_server


def main() -> None:
    """
    Demonstrate intermittent solar forecast failures with a short-lived cache.
    """
    # Accelerate cache refreshes for this demo only; production defaults remain unchanged.
    Constants.SOLAR_FORECAST_YOUNG = timedelta(seconds=1)
    Constants.SOLAR_FORECAST_OLD = timedelta(seconds=3)

    run_failing_server(
        'intermittent solar forecast',
        forecaster_failure=DummyForecasterFailure(
            location=FailureLocation.get_forecast,
            probability=0.5,
            exception=TimeoutError('Simulated intermittent solar forecast timeout'),
        ),
    )


if __name__ == '__main__':
    main()
