"""Songkick API integration — gap-fill for smaller concerts Ticketmaster misses.

Songkick gates new API access; this module is implemented but will gracefully no-op if
SONGKICK_API_KEY is not configured. Add the key to enable.
"""

from datetime import date, timedelta
from typing import Any

import httpx

from newsletter.config import Settings
from newsletter.logging_config import get_logger
from newsletter.models import CandidateEvent, EventSource

log = get_logger(__name__)

SONGKICK_URL = "https://api.songkick.com/api/3.0/metro_areas/{metro_id}/calendar.json"

# Charlotte metro area ID on Songkick. Sourced from
# https://api.songkick.com/api/3.0/search/locations.json?query=Charlotte
CHARLOTTE_METRO_ID = "9357"


def _parse_event(raw: dict[str, Any]) -> CandidateEvent | None:
    try:
        venue = raw.get("venue", {})
        return CandidateEvent(
            id=str(raw["id"]),
            source=EventSource.SONGKICK,
            title=raw.get("displayName") or "(no title)",
            start=raw["start"]["datetime"] or raw["start"]["date"],
            venue=venue.get("displayName"),
            venue_neighborhood=venue.get("metroArea", {}).get("displayName"),
            url=raw["uri"],
            image_url=None,
            category="Music",
            subcategory=None,
        )
    except (KeyError, ValueError) as exc:
        log.warning("songkick.parse_skipped", reason=str(exc))
        return None


def fetch_songkick_events(settings: Settings, *, days_ahead: int = 14) -> list[CandidateEvent]:
    """Fetch upcoming Songkick events for Charlotte metro. No-ops if no API key."""
    # pydantic-settings reads `SONGKICK_API_KEY=` (empty after the equals) as SecretStr(""),
    # not None, so check both. Otherwise we send a request with an empty key and 401.
    if settings.songkick_api_key is None or not settings.songkick_api_key.get_secret_value():
        log.info("songkick.skipped", reason="no api key configured")
        return []

    min_date = date.today()
    max_date = min_date + timedelta(days=days_ahead)

    params: dict[str, str | int] = {
        "apikey": settings.songkick_api_key.get_secret_value(),
        "min_date": min_date.isoformat(),
        "max_date": max_date.isoformat(),
        "per_page": 50,
    }

    url = SONGKICK_URL.format(metro_id=CHARLOTTE_METRO_ID)
    log.info("songkick.fetch", days_ahead=days_ahead)
    response = httpx.get(url, params=params, timeout=30.0)
    response.raise_for_status()
    payload = response.json()

    raw_events = payload.get("resultsPage", {}).get("results", {}).get("event", [])
    events = [evt for raw in raw_events if (evt := _parse_event(raw)) is not None]
    log.info("songkick.fetched", total=len(events))
    return events
