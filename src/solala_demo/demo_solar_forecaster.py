from datetime import date

import local_config as config
from solala.delegates.solar_forecaster import OpenMeteoForecaster


def main():
    forecaster = OpenMeteoForecaster(
        latitude=config.LATITUDE,
        longitude=config.LONGITUDE,
        panel_tilt=config.PANEL_TILT,
        panel_orientation=config.PANEL_ORIENTATION,
        panel_capacity=config.PANEL_CAPACITY,
        inverter_limit=config.INVERTER_LIMIT,
    )

    for forecast in forecaster.get_forecast(date.today()):
        print(forecast.to_json(datetime_format='%Y-%m-%d %H:%M:%S'))


if __name__ == '__main__':
    main()
