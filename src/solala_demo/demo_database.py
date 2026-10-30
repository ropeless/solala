from datetime import datetime

import local_config as config
from solala.control_loop.modes_and_policies import BatteryMode, BatteryPolicy, InverterMode, InverterPolicy
from solala.database.solala_database import Measurement, SolalaConnections


def main() -> None:
    with SolalaConnections(config.DATABASE_APP_URL) as pool:
        with pool.solala_data() as db:
            measurement = Measurement(
                timestamp=datetime.now(),

                solar_power=12,
                grid_power=23,
                house_power=34,
                battery_power=45,
                battery_charge=56,

                buy_price=67,
                feed_in_price=78,

                accumulated_solar_energy=123,
                accumulated_grid_energy_draw=345,
                accumulated_grid_energy_feed_in=678,

                battery_mode=BatteryMode.ENABLE,
                battery_policy=BatteryPolicy.MANUAL,
                inverter_mode=InverterMode.ENABLE,
                inverter_policy=InverterPolicy.MANUAL,
            )
            db.insert_measurement(measurement)
            got = db.get_latest_measurement()
            print(got)


if __name__ == "__main__":
    main()
