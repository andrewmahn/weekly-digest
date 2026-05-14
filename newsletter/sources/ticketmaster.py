from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from newsletter.config import Settings
from newsletter.logging_config import get_logger
from newsletter.models import CandidateEvent, EventSource

log = get_logger(__name__)

TICKETMASTER_URL = "https://app.ticketmaster.com/discovery/v2/events.json"


def _parse_event(raw: dict[str, Any]) -> CandidateEvent | None:
    try:
        local_date = raw["dates"]["start"].get("localDate")
        local_time = raw["dates"]["start"].get("localTime", "20:00:00")
        if not local_date:
            return None
        start = datetime.fromisoformat(f"{local_date}T{local_time}")

        venues = raw.get("_embedded", {}).get("venues", [])
        venue_name = venues[0]["name"] if venues else None
        neighborhood = venues[0].get("city", {}).get("name") if venues else None

        images = raw.get("images", [])
        image_url = images[0]["url"] if images else None

        classifications = raw.get("classifications", [])
        category = classifications[0].get("segment", {}).get("name") if classifications else None
        subcategory = classifications[0].get("genre", {}).get("name") if classifications else None

        price_ranges = raw.get("priceRanges", [])
        price = None
        min_price = None
        if price_ranges:
            pr = price_ranges[0]
            min_price = float(pr["min"]) if pr.get("min") is not None else None
            price = f"${pr.get('min', 0):.0f}–${pr.get('max', 0):.0f}"  # noqa: RUF001 — intentional en-dash for display

        return CandidateEvent(
            id=raw["id"],
            source=EventSource.TICKETMASTER,
            title=raw["name"],
            start=start,
            venue=venue_name,
            venue_neighborhood=neighborhood,
            url=raw["url"],
            image_url=image_url,
            category=category,
            subcategory=subcategory,
            price_range=price,
            min_price=min_price,
            description=raw.get("info") or raw.get("pleaseNote"),
        )
    except (KeyError, ValueError) as exc:
        log.warning("ticketmaster.parse_skipped", reason=str(exc), event_id=raw.get("id"))
        return None


def fetch_ticketmaster_events(
    settings: Settings, *, days_ahead: int = 60, size: int = 100
) -> list[CandidateEvent]:
    """Fetch upcoming events near the configured city from the Ticketmaster Discovery API.

    Pulls a 60-day window so mainstream concerts with sell-out risk surface 3+ weeks
    out. The lead-time filter in main.py drops same-week shows and gates expensive
    events behind a 21-day cutoff; the ranking layer then picks the most relevant.
    """
    now = datetime.now(UTC)
    end = now + timedelta(days=days_ahead)

    params: dict[str, Any] = {
        "apikey": settings.ticketmaster_api_key.get_secret_value(),
        "city": settings.city_name,
        "stateCode": settings.city_state,
        "countryCode": "US",
        "size": size,
        "sort": "date,asc",
        "startDateTime": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "endDateTime": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }

    log.info("ticketmaster.fetch", city=settings.city_name, days_ahead=days_ahead)
    response = httpx.get(TICKETMASTER_URL, params=params, timeout=30.0)
    response.raise_for_status()
    payload = response.json()

    raw_events = payload.get("_embedded", {}).get("events", [])
    events = [evt for raw in raw_events if (evt := _parse_event(raw)) is not None]
    log.info("ticketmaster.fetched", total=len(events))
    return events
