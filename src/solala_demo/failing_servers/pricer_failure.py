from solala.delegates.power_pricer.dummy_power_pricer.dummy_power_pricer import FailureLocation
from solala.settings import DummyPricerFailure
from solala_demo.failing_servers.common import run_failing_server


def main() -> None:
    """
    Demonstrate persistent electricity price retrieval failures.
    """
    run_failing_server(
        'electricity price timeout',
        pricer_failure=DummyPricerFailure(
            location=FailureLocation.get_price,
            exception=TimeoutError('Simulated electricity price timeout'),
        ),
    )


if __name__ == '__main__':
    main()
