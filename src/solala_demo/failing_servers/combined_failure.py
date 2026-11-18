from solala.delegates.power_consumer.dummy_power_consumer.dummy_power_consumer import (
    FailureLocation as ConsumerFailureLocation,
)
from solala.delegates.power_controller.dummy_power_controller.dummy_power_controller import (
    FailureLocation as ControllerFailureLocation,
)
from solala.settings import DummyConsumerFailure, DummyControllerFailure
from solala_demo.failing_servers.common import run_failing_server


def main() -> None:
    """
    Demonstrate simultaneous controller and consumer status failures.
    """
    run_failing_server(
        'combined controller and consumer timeouts',
        controller_failure=DummyControllerFailure(
            location=ControllerFailureLocation.get_status,
            exception=TimeoutError('Simulated controller status timeout'),
        ),
        consumer_failure=DummyConsumerFailure(
            location=ConsumerFailureLocation.get_status,
            exception=TimeoutError('Simulated consumer status timeout'),
        ),
    )


if __name__ == '__main__':
    main()
