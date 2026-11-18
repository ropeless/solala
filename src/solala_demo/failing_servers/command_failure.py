from solala.delegates.power_controller.dummy_power_controller.dummy_power_controller import (
    FailureLocation,
)
from solala.settings import DummyControllerFailure
from solala_demo.failing_servers.common import run_failing_server


def main() -> None:
    """
    Demonstrate a persistent inverter command failure and WARNING alarm.

    The GUI user should set the inverter to DISABLE to initiate the failure.
    """
    run_failing_server(
        'inverter command timeout',
        controller_failure=DummyControllerFailure(
            location=FailureLocation.disable_inverter,
            exception=TimeoutError('Simulated inverter disable timeout'),
        ),
    )


if __name__ == '__main__':
    main()
