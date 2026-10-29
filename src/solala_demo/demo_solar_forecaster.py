import asyncio
from datetime import date

import local_config as config
from solala.delegates.solar_forecaster.open_meteo_forecaster.open_meteo_forecaster import OpenMeteoForecaster
from solala.delegates.solar_forecaster.solar_forecaster import DailySolarForecast


async def main():
    forecaster = OpenMeteoForecaster(
        latitude=config.LATITUDE,
        longitude=config.LONGITUDE,
        panel_tilt=config.PANEL_TILT,
        panel_orientation=config.PANEL_ORIENTATION,
        panel_capacity=config.PANEL_CAPACITY,
        inverter_limit=config.INVERTER_LIMIT,
    )

    daily_forecast: DailySolarForecast = await forecaster.get_forecast(date.today())

    for forecast in daily_forecast:
        print(forecast.to_json(datetime_format='%Y-%m-%d %H:%M:%S'))


if __name__ == '__main__':
    asyncio.run(main())
