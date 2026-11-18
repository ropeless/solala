from solala.delegates.power_controller.dummy_power_controller.dummy_power_controller import (
    FailureLocation,
)
from solala.settings import DummyControllerFailure
from solala_demo.failing_servers.common import run_failing_server


def main() -> None:
    """
    Demonstrate recovery from controller status failures without restarting.

    The first ten status reads fail. Subsequent reads succeed, clearing the
    CAUTION issue when the next successful status request is made.
    """
    run_failing_server(
        'recovering controller status',
        controller_failure=DummyControllerFailure(
            location=FailureLocation.get_status,
            exception=TimeoutError('Simulated temporary controller timeout'),
            max_injections=10,
        ),
    )


if __name__ == '__main__':
    main()
