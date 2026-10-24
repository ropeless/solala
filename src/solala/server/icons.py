from typing import Optional

from solala.solar_forecaster.solar_forecaster import WeatherCode


def diagnostic_name_to_icon_url(diagnostic_name: str) -> str:
    return f'/images/diagnostic-icons/{diagnostic_name.lower()}.svg'


def weather_code_to_icon_url(code: WeatherCode, animated: bool = False) -> Optional[str]:
    subdirectory = 'animated' if animated else 'static'
    icon_name: Optional[str] = weather_code_to_icon_name(code)
    if icon_name is None:
        return None
    else:
        return f'/images/weather-icons/{subdirectory}/{icon_name}.svg'


def weather_code_to_icon_name(code: WeatherCode) -> Optional[str]:
    match code:
        case WeatherCode.CLEAR_DAY:
            return 'clear-day'
        case WeatherCode.CLOUDY_1:
            return 'cloudy-1-day'
        case WeatherCode.CLOUDY_2:
            return 'cloudy-2-day'
        case WeatherCode.CLOUDY_3:
            return 'cloudy-3-day'
        case WeatherCode.CLOUDY_4:
            return 'cloudy'
        case WeatherCode.DUST:
            return 'dust'
        case WeatherCode.FOG:
            return 'fog-day'
        case WeatherCode.FROST:
            return 'frost-day'
        case WeatherCode.HAIL:
            return 'hail'
        case WeatherCode.HAZE:
            return 'haze-day'
        case WeatherCode.RAINY_1:
            return 'rainy-1-day'
        case WeatherCode.RAINY_2:
            return 'rainy-2-day'
        case WeatherCode.RAINY_3:
            return 'rainy-3-day'
        case WeatherCode.THUNDERSTORMS:
            return 'thunderstorms'
        case WeatherCode.THUNDERSTORMS_ISOLATED:
            return 'isolated-thunderstorms'
        case WeatherCode.THUNDERSTORMS_SCATTERED:
            return 'scattered-thunderstorms'
        case WeatherCode.THUNDERSTORM_SEVERE:
            return 'severe-thunderstorms'
        case WeatherCode.HURRICANE:
            return 'hurricane'
        case WeatherCode.TORNADO:
            return 'tornado'
        case WeatherCode.SNOWY_1:
            return 'snowy-1-day'
        case WeatherCode.SNOWY_2:
            return 'snowy-2-day'
        case WeatherCode.SNOWY_3:
            return 'snowy-3-day'
        case WeatherCode.RAIN_AND_SLEET_MIX:
            return 'rain-and-sleet-mix'
        case WeatherCode.RAIN_AND_SNOW_MIX:
            return 'rain-and-snow-mix'
        case WeatherCode.SNOW_AND_SLEET_MIX:
            return 'snow-and-sleet-mix'

    return None
