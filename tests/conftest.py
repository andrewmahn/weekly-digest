"""Shared pytest fixtures."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from newsletter.config import Settings
from newsletter.models import (
    CalendarEvent,
    CandidateEvent,
    DayForecast,
    DealPick,
    DealType,
    EventSource,
    NewsletterContext,
    Preferences,
    RankedEvent,
    WeatherForecast,
)


@pytest.fixture
def settings() -> Settings:
    """A Settings instance populated with placeholder values for unit tests."""
    return Settings(
        google_client_id="fake-client-id",
        google_client_secret="fake-client-secret",
        google_refresh_token="fake-refresh-token",
        google_calendar_ids="primary",
        ticketmaster_api_key="fake-tm-key",
        anthropic_api_key="fake-anthropic-key",
        resend_api_key="fake-resend-key",
        newsletter_from_email="from@example.com",
        newsletter_to_emails="to1@example.com,to2@example.com",
    )


@pytest.fixture
def sample_calendar_events() -> list[CalendarEvent]:
    return [
        CalendarEvent(
            id="cal1",
            calendar_id="primary",
            title="Brunch with Sarah",
            start=datetime(2026, 5, 17, 11, 0, tzinfo=UTC),
            end=datetime(2026, 5, 17, 13, 0, tzinfo=UTC),
            location="Optimist Hall",
        ),
        CalendarEvent(
            id="cal2",
            calendar_id="primary",
            title="Yoga class",
            start=datetime(2026, 5, 18, 18, 0, tzinfo=UTC),
            end=datetime(2026, 5, 18, 19, 0, tzinfo=UTC),
        ),
    ]


@pytest.fixture
def sample_weather() -> WeatherForecast:
    return WeatherForecast(
        location="Charlotte, NC",
        days=[
            DayForecast(
                date=date(2026, 5, 17),
                high_f=78.0,
                low_f=62.0,
                precipitation_chance=10,
                condition="Mostly clear",
            ),
            DayForecast(
                date=date(2026, 5, 18),
                high_f=82.0,
                low_f=65.0,
                precipitation_chance=45,
                condition="Rain showers",
            ),
        ],
    )


@pytest.fixture
def sample_candidates() -> list[CandidateEvent]:
    return [
        CandidateEvent(
            id="tm1",
            source=EventSource.TICKETMASTER,
            title="Big Thief at The Fillmore",
            start=datetime(2026, 5, 20, 20, 0),
            venue="The Fillmore Charlotte",
            url="https://www.ticketmaster.com/event/tm1",
            category="Music",
            subcategory="Indie Folk",
            price_range="$45–$85",  # noqa: RUF001 — intentional en-dash for display
        ),
        CandidateEvent(
            id="tm2",
            source=EventSource.TICKETMASTER,
            title="Hornets vs Lakers",
            start=datetime(2026, 5, 21, 19, 30),
            venue="Spectrum Center",
            url="https://www.ticketmaster.com/event/tm2",
            category="Sports",
        ),
    ]


@pytest.fixture
def sample_preferences() -> Preferences:
    return Preferences(
        music_genres=["indie folk", "jazz"],
        cuisine_likes=["southern", "thai"],
        venue_types=["intimate venues"],
        activity_patterns=["dinner-then-show on Fridays"],
        recent_event_titles=["Vampire Weekend show", "Optimist Hall brunch"],
        built_at=datetime(2026, 5, 1, tzinfo=UTC),
        source_event_count=42,
    )


@pytest.fixture
def sample_ranked_events(sample_candidates: list[CandidateEvent]) -> list[RankedEvent]:
    return [
        RankedEvent(
            event=sample_candidates[0],
            reason="Indie folk show at The Fillmore — similar to the Vampire Weekend show you went to last month.",
            rank=1,
        ),
    ]


@pytest.fixture
def sample_deals() -> list[DealPick]:
    return [
        DealPick(
            title="Half-price oysters",
            description="Local seafood spot runs half-price oysters every Tuesday from 5 to 7pm.",
            venue="The Stanley",
            neighborhood="Elizabeth",
            deal_type=DealType.HAPPY_HOUR,
            when="Tuesdays 5–7pm",  # noqa: RUF001 — intentional en-dash for display
            source_url="https://example.com/stanley-happy-hour",
        ),
        DealPick(
            title="Free outdoor movie: The Princess Bride",
            description="Romare Bearden Park screening with food trucks; bring a blanket.",
            venue="Romare Bearden Park",
            neighborhood="Uptown",
            deal_type=DealType.FREE_EVENT,
            when="Friday, May 22, 8pm",
            source_url="https://example.com/uptown-movie-night",
        ),
    ]


@pytest.fixture
def sample_context(
    sample_calendar_events: list[CalendarEvent],
    sample_weather: WeatherForecast,
    sample_ranked_events: list[RankedEvent],
    sample_deals: list[DealPick],
) -> NewsletterContext:
    return NewsletterContext(
        generated_at=datetime(2026, 5, 17, 11, 7, tzinfo=UTC),
        week_start=date(2026, 5, 17),
        week_end=date(2026, 5, 23),
        city_name="Charlotte, NC",
        calendar_events=sample_calendar_events,
        weather=sample_weather,
        ranked_events=sample_ranked_events,
        deals=sample_deals,
    )
