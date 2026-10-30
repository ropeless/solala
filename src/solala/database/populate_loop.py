import asyncio
from datetime import datetime, UTC, timedelta

from nicegui import ui

from solala.control_loop import control_loop
from solala.control_loop.control_loop import ControlMode
from solala.database.solala_database import Measurement, SolalaConnections
from solala.logger import LOGGER
from solala.power_pricer.power_pricer import Price


class DatabasePopulator:

    def __init__(self, connection_string: str):
        self._pool = SolalaConnections(connection_string)

        ui.on_startup(lambda: asyncio.create_task(self.measurement_loop()))

    async def measurement_loop(self) -> None:
        while True:
            now: datetime = datetime.now(UTC)

            next_run: datetime = now.replace(second=0, microsecond=0, minute=(now.minute // 5))
            next_run += timedelta(minutes=5)

            await asyncio.sleep((next_run - now).total_seconds())

            try:
                measurement: Measurement = await collect_measurement()
                with self._pool.solala_data() as db:
                    db.insert_measurement(measurement)

            except Exception:
                LOGGER.exception('Failed to collect or store measurement')


async def collect_measurement() -> Measurement:
    timestamp = datetime.now(UTC)

    # Read current values from your existing functions.
    solar_power = await get_solar_power()
    grid_power = await get_grid_power()
    house_power = await get_house_power()
    battery_power = await get_battery_power()
    battery_charge = await get_battery_charge()

    # Read cumulative energy counters.
    solar_energy = await get_accumulated_solar_energy()
    grid_energy_draw = await get_accumulated_grid_energy_draw()
    grid_energy_feed_in = await get_accumulated_grid_energy_feed_in()

    price: Price = control_loop.get_price_now()
    control_mode: ControlMode = control_loop.get_control_mode()

    return Measurement(
        timestamp=timestamp,
        solar_power=solar_power,
        grid_power=grid_power,
        house_power=house_power,
        battery_power=battery_power,
        battery_charge=battery_charge,
        buy_price=price.buy_price,
        feed_in_price=price.feed_in_price,
        accumulated_solar_energy=solar_energy,
        accumulated_grid_energy_draw=grid_energy_draw,
        accumulated_grid_energy_feed_in=grid_energy_feed_in,
        battery_mode=control_mode.battery_mode,
        battery_policy=control_mode.battery_policy,
        inverter_mode=control_mode.inverter_mode,
        inverter_policy=control_mode.inverter_policy,
    )
