from datetime import date, datetime, timedelta

import httpx

from newsletter.config import Settings
from newsletter.logging_config import get_logger
from newsletter.models import DayForecast, WeatherForecast

log = get_logger(__name__)

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"

# Map Open-Meteo WMO weather codes → human-readable conditions.
# Reference: https://open-meteo.com/en/docs#weathervariables (Weather code section).
_WEATHER_CODE: dict[int, str] = {
    0: "Clear",
    1: "Mostly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Foggy",
    48: "Foggy",
    51: "Light drizzle",
    53: "Drizzle",
    55: "Heavy drizzle",
    61: "Light rain",
    63: "Rain",
    65: "Heavy rain",
    71: "Light snow",
    73: "Snow",
    75: "Heavy snow",
    80: "Rain showers",
    81: "Rain showers",
    82: "Heavy showers",
    95: "Thunderstorms",
    96: "Thunderstorms",
    99: "Severe thunderstorms",
}


def _describe(code: int) -> str:
    return _WEATHER_CODE.get(code, "Unknown")


def fetch_weather(settings: Settings, *, start: date | None = None) -> WeatherForecast:
    """Fetch a 7-day forecast from Open-Meteo for the configured city.

    Open-Meteo is keyless and rate-limit-friendly for personal use. We request daily
    aggregates (high/low/condition/precipitation chance) in Fahrenheit, aligned to the
    configured timezone so day boundaries match local experience.
    """
    start = start or date.today()
    end = start + timedelta(days=6)

    params: dict[str, str | float] = {
        "latitude": settings.city_lat,
        "longitude": settings.city_lon,
        "daily": ",".join(
            [
                "weather_code",
                "temperature_2m_max",
                "temperature_2m_min",
                "precipitation_probability_max",
                "sunrise",
                "sunset",
            ]
        ),
        "temperature_unit": "fahrenheit",
        "timezone": settings.timezone,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
    }

    log.info("weather.fetch", lat=settings.city_lat, lon=settings.city_lon, start=str(start))

    response = httpx.get(OPEN_METEO_URL, params=params, timeout=15.0)
    response.raise_for_status()
    payload = response.json()
    daily = payload["daily"]

    days: list[DayForecast] = []
    for i, day_str in enumerate(daily["time"]):
        days.append(
            DayForecast(
                date=date.fromisoformat(day_str),
                high_f=daily["temperature_2m_max"][i],
                low_f=daily["temperature_2m_min"][i],
                precipitation_chance=daily["precipitation_probability_max"][i] or 0,
                condition=_describe(daily["weather_code"][i]),
                sunrise=datetime.fromisoformat(daily["sunrise"][i])
                if daily.get("sunrise")
                else None,
                sunset=datetime.fromisoformat(daily["sunset"][i]) if daily.get("sunset") else None,
            )
        )

    forecast = WeatherForecast(location=f"{settings.city_name}, {settings.city_state}", days=days)
    log.info("weather.fetched", days=len(days))
    return forecast
