from enum import Enum, auto


class WeatherCode(Enum):
    """
    Weather conditions represented in Solala solar forecasts.
    """

    # Night and clear conditions.
    NIGHT = auto()
    CLEAR_DAY = auto()

    # Cloud cover.
    CLOUDY_1 = auto()
    CLOUDY_2 = auto()
    CLOUDY_3 = auto()
    CLOUDY_4 = auto()

    # Atmospheric conditions.
    DUST = auto()
    FOG = auto()
    FROST = auto()
    HAIL = auto()
    HAZE = auto()

    # Rain.
    RAINY_1 = auto()
    RAINY_2 = auto()
    RAINY_3 = auto()

    # Thunderstorms and severe weather.
    THUNDERSTORMS = auto()
    THUNDERSTORMS_ISOLATED = auto()
    THUNDERSTORMS_SCATTERED = auto()
    THUNDERSTORM_SEVERE = auto()
    HURRICANE = auto()
    TORNADO = auto()

    # Snow and mixed precipitation.
    SNOWY_1 = auto()
    SNOWY_2 = auto()
    SNOWY_3 = auto()

    RAIN_AND_SLEET_MIX = auto()
    RAIN_AND_SNOW_MIX = auto()
    SNOW_AND_SLEET_MIX = auto()

    # Unknown conditions.
    UNKNOWN = auto()
