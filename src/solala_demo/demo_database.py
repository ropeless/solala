import asyncio
import json
import selectors
from datetime import datetime
from typing import Optional

from local_config_help import config
from solala.control_loop.modes_and_policies import BatteryMode, BatteryPolicy, InverterMode, InverterPolicy
from solala.database.solala_database import Measurement, SolalaDatabase
from solala.database.solala_database_connections import solala_database
from solala.delegates.solar_forecaster.weather_code import WeatherCode
from solala.utils.json_extras import to_json


async def insert_measurement(db: SolalaDatabase) -> None:
    measurement = Measurement(
        timestamp=datetime.now(),

        solar_power=12,
        grid_power=23,
        house_power=34,
        battery_power=45,
        battery_charge=56,

        buy_price=67,
        feed_in_price=78,
        renewables=66,

        accumulated_solar_energy=123,
        accumulated_grid_energy_import=345,
        accumulated_grid_energy_export=678,
        accumulated_battery_energy_charge=890,
        accumulated_battery_energy_discharge=901,

        battery_mode=BatteryMode.ENABLE,
        battery_policy=BatteryPolicy.MANUAL,
        inverter_mode=InverterMode.ENABLE,
        inverter_policy=InverterPolicy.MANUAL,

        forecast_irradiance=543,
        forecast_temperature=432,
        forecast_power=321,
        forecast_weather=WeatherCode.CLEAR_DAY,

    )
    await db.insert_measurement(measurement)


async def main() -> None:
    async with solala_database(
            role=config.DATABASE_APP_ROLE,
            password=config.DATABASE_APP_PASSWORD,
            host=config.DATABASE_HOST,
            port=config.DATABASE_PORT,
            database_name=config.DATABASE_NAME,
    ) as db:
        await insert_measurement(db)
        got: Optional[Measurement] = await db.get_latest_measurement()

        if got is not None:
            to_print = json.dumps(to_json(got), indent=4)
            print(to_print)
        else:
            print('No measurement in database')


if __name__ == "__main__":
    asyncio.run(
        main(),
        loop_factory=(lambda: asyncio.SelectorEventLoop(selectors.SelectSelector())),
    )
