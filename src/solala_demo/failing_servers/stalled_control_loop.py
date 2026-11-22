from solala.delegates.power_controller.dummy_power_controller.dummy_power_controller import (
    FailureLocation,
)
from solala.settings import DummyControllerFailure
from solala_demo.failing_servers._common import run_failing_server


def main() -> None:
    """
    Demonstrate a temporary control-loop stall during a battery command.

    Wait for System Health to show LIVE, then select Disable Battery in the UI to
    trigger an 18-second asynchronous delay. The command succeeds afterward,
    allowing the control loop and master alarm to recover automatically.
    """
    run_failing_server(
        'temporary battery command stall',
        controller_failure=DummyControllerFailure(
            location=FailureLocation.disable_battery,
            sleep=18.0,
        ),
    )


if __name__ == '__main__':
    main()
