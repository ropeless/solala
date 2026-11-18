from solala.delegates.power_consumer.dummy_power_consumer.dummy_power_consumer import (
    FailureLocation,
)
from solala.settings import DummyConsumerConnection, DummyConsumerFailure
from solala_demo.failing_servers.common import run_failing_server


def main() -> None:
    """
    Demonstrate persistent example consumer status failures.
    """
    run_failing_server(
        'consumer status timeout',
        consumer=DummyConsumerConnection(
            current=5,
            failure=DummyConsumerFailure(
                location=FailureLocation.get_status,
                exception=TimeoutError('Simulated consumer status timeout'),
            ),
        ),
    )


if __name__ == '__main__':
    main()
