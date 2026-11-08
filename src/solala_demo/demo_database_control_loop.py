import asyncio
import selectors
from datetime import date

import local_config as config
from solala.control_loop import control_loop
from solala.database.measurement import Measurement
from solala.settings import Settings, DatabaseConnection, DummyControllerConnection, DummyPricerConnection, \
    DummySolarForecasterConnection


async def main() -> None:
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

    asyncio.create_task(control_loop.control_loop(settings=settings))
    await asyncio.sleep(1)

    async with control_loop.solala_database() as db:
        measurement: Measurement
        for measurement in await db.get_measurements(date.today()):
            print(measurement)
        print('done.')


if __name__ == "__main__":
    asyncio.run(
        main(),
        loop_factory=(lambda: asyncio.SelectorEventLoop(selectors.SelectSelector())),
    )
