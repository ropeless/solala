import asyncio
import selectors
from datetime import date

from solala.utils.local_config_help import config
from solala.control_loop import control_loop
from solala.settings import Settings, DatabaseConnection, DummyControllerConnection, DummyPricerConnection, \
    DummySolarForecasterConnection


async def main() -> None:
    """
    Run the control loop briefly and display today's database measurements.
    """
    settings = Settings(
        database=DatabaseConnection(
            role=config.DATABASE_APP_ROLE,
            password=config.DATABASE_APP_PASSWORD,
            host=config.DATABASE_HOST,
            port=config.DATABASE_PORT,
            database_name=config.DATABASE_NAME,
        ),

        controller=DummyControllerConnection(),
        pricer=DummyPricerConnection(),
        forecaster=DummySolarForecasterConnection(),
    )

    task: asyncio.Task[None] = asyncio.create_task(control_loop.control_loop(settings=settings))
    try:
        await asyncio.sleep(1)
        for measurement in await control_loop.solala_database_measurements(date.today()):
            print(measurement)
        print('done.')
    finally:
        control_loop.exit_control_loop()
        await task


if __name__ == "__main__":
    asyncio.run(
        main(),
        loop_factory=(lambda: asyncio.SelectorEventLoop(selectors.SelectSelector())),
    )
