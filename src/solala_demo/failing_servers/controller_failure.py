from solala.delegates.power_controller.dummy_power_controller.dummy_power_controller import (
    FailureLocation,
)
from solala.settings import DummyControllerConnection, DummyControllerFailure
from solala_demo.failing_servers.common import run_failing_server


def main() -> None:
    """
    Demonstrate persistent power controller status failures.
    """
    run_failing_server(
        'controller status timeout',
        controller=DummyControllerConnection(
            failure=DummyControllerFailure(
                location=FailureLocation.get_status,
                exception=TimeoutError('Simulated controller status timeout'),
            ),
        ),
    )


if __name__ == '__main__':
    main()
