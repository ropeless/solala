from solala.delegates.power_controller.dummy_power_controller.dummy_power_controller import (
    FailureLocation,
)
from solala.settings import DummyControllerFailure
from solala_demo.failing_servers._common import run_failing_server


def main() -> None:
    """
    Demonstrate a one-shot battery command failure and WARNING alarm.

    The GUI user should set the battery to DISABLE to initiate the failure.
    """
    run_failing_server(
        'battery command timeout',
        controller_failure=DummyControllerFailure(
            location=FailureLocation.disable_battery,
            exception=TimeoutError('Simulated battery disable timeout'),
        ),
    )


if __name__ == '__main__':
    main()
