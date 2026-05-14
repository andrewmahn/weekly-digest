"""Source tests with respx to mock external HTTP calls.

We test the parse path — given a realistic API response, does our source produce
correctly-typed model objects? Network is mocked; no real keys required.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from newsletter.config import Settings
from newsletter.sources.ticketmaster import TICKETMASTER_URL, fetch_ticketmaster_events
from newsletter.sources.weather import OPEN_METEO_URL, fetch_weather


@respx.mock
def test_weather_parses_open_meteo(settings: Settings) -> None:
    respx.get(OPEN_METEO_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "daily": {
                    "time": ["2026-05-17", "2026-05-18"],
                    "weather_code": [1, 80],
                    "temperature_2m_max": [78.2, 82.5],
                    "temperature_2m_min": [62.1, 65.0],
                    "precipitation_probability_max": [10, 45],
                    "sunrise": ["2026-05-17T06:21", "2026-05-18T06:20"],
                    "sunset": ["2026-05-17T20:15", "2026-05-18T20:16"],
                }
            },
        )
    )

    forecast = fetch_weather(settings)

    assert forecast.location == "Charlotte, NC"
    assert len(forecast.days) == 2
    assert forecast.days[0].condition == "Mostly clear"
    assert forecast.days[1].condition == "Rain showers"
    assert forecast.days[0].high_f == 78.2
    assert forecast.days[1].precipitation_chance == 45


@respx.mock
def test_ticketmaster_parses_events(settings: Settings) -> None:
    respx.get(TICKETMASTER_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "_embedded": {
                    "events": [
                        {
                            "id": "tm-1",
                            "name": "Big Thief",
                            "url": "https://www.ticketmaster.com/event/tm-1",
                            "dates": {
                                "start": {"localDate": "2026-05-20", "localTime": "20:00:00"}
                            },
                            "_embedded": {
                                "venues": [{"name": "The Fillmore", "city": {"name": "Charlotte"}}]
                            },
                            "images": [{"url": "https://example.com/img.jpg"}],
                            "classifications": [
                                {"segment": {"name": "Music"}, "genre": {"name": "Indie"}}
                            ],
                            "priceRanges": [{"min": 45.0, "max": 85.0}],
                        }
                    ]
                }
            },
        )
    )

    events = fetch_ticketmaster_events(settings)

    assert len(events) == 1
    e = events[0]
    assert e.title == "Big Thief"
    assert e.venue == "The Fillmore"
    assert e.category == "Music"
    assert e.subcategory == "Indie"
    assert e.price_range == "$45–$85"  # noqa: RUF001 — intentional en-dash for display


@respx.mock
def test_ticketmaster_skips_malformed_event(settings: Settings) -> None:
    respx.get(TICKETMASTER_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "_embedded": {
                    "events": [
                        # missing required keys → should be silently skipped
                        {"id": "broken"},
                        {
                            "id": "tm-good",
                            "name": "Good Show",
                            "url": "https://www.ticketmaster.com/event/good",
                            "dates": {
                                "start": {"localDate": "2026-05-20", "localTime": "20:00:00"}
                            },
                        },
                    ]
                }
            },
        )
    )

    events = fetch_ticketmaster_events(settings)
    assert len(events) == 1
    assert events[0].id == "tm-good"


@respx.mock
def test_weather_raises_on_5xx(settings: Settings) -> None:
    respx.get(OPEN_METEO_URL).mock(return_value=httpx.Response(503))
    with pytest.raises(httpx.HTTPStatusError):
        fetch_weather(settings)
