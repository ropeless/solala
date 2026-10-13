import local_config as config
from solala.solar_forecaster.open_meteo_forecaster.open_meteo_forecaster import OpenMeteoForecaster


def main():
    forecaster = OpenMeteoForecaster(
        latitude=config.LATITUDE,
        longitude=config.LONGITUDE,
        panel_tilt=config.PANEL_TILT,
        panel_orientation=config.PANEL_ORIENTATION,
        panel_capacity=config.PANEL_CAPACITY,
        inverter_limit=config.INVERTER_LIMIT,
    )

    for forecast in forecaster.get_forecast(0):
        print(forecast.to_json(datetime_format='%Y-%m-%d %H:%M:%S'))


if __name__ == '__main__':
    main()
