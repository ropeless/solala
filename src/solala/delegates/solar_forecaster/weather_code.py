from enum import Enum, auto


class WeatherCode(Enum):
    NIGHT = auto()

    CLEAR_DAY = auto()

    CLOUDY_1 = auto()
    CLOUDY_2 = auto()
    CLOUDY_3 = auto()
    CLOUDY_4 = auto()

    DUST = auto()
    FOG = auto()
    FROST = auto()
    HAIL = auto()
    HAZE = auto()

    RAINY_1 = auto()
    RAINY_2 = auto()
    RAINY_3 = auto()

    THUNDERSTORMS = auto()
    THUNDERSTORMS_ISOLATED = auto()
    THUNDERSTORMS_SCATTERED = auto()
    THUNDERSTORM_SEVERE = auto()
    HURRICANE = auto()
    TORNADO = auto()

    SNOWY_1 = auto()
    SNOWY_2 = auto()
    SNOWY_3 = auto()

    RAIN_AND_SLEET_MIX = auto()
    RAIN_AND_SNOW_MIX = auto()
    SNOW_AND_SLEET_MIX = auto()

    UNKNOWN = auto()
