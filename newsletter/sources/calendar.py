from datetime import UTC, datetime, timedelta
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from newsletter.config import Settings
from newsletter.logging_config import get_logger
from newsletter.models import CalendarEvent

log = get_logger(__name__)

SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]
TOKEN_URI = "https://oauth2.googleapis.com/token"


def _build_credentials(settings: Settings) -> Credentials:
    """Construct OAuth credentials from the stored refresh token and exchange for an access token."""
    # google-auth ships partial type info; the Credentials constructor and .refresh()
    # are untyped at the stub level, so silence the strict-mode check here.
    creds = Credentials(  # type: ignore[no-untyped-call]
        token=None,
        refresh_token=settings.google_refresh_token.get_secret_value(),
        token_uri=TOKEN_URI,
        client_id=settings.google_client_id.get_secret_value(),
        client_secret=settings.google_client_secret.get_secret_value(),
        scopes=SCOPES,
    )
    creds.refresh(Request())  # type: ignore[no-untyped-call]
    return creds


def _parse_event(raw: dict[str, Any], calendar_id: str) -> CalendarEvent | None:
    """Convert a Google Calendar API event dict to our CalendarEvent.

    Returns None for events we can't represent (e.g. cancelled, no start time).
    """
    if raw.get("status") == "cancelled":
        return None

    start_raw = raw.get("start", {})
    end_raw = raw.get("end", {})

    if "dateTime" in start_raw:
        start = datetime.fromisoformat(start_raw["dateTime"])
        end = datetime.fromisoformat(end_raw["dateTime"])
        all_day = False
    elif "date" in start_raw:
        start = datetime.fromisoformat(start_raw["date"]).replace(tzinfo=UTC)
        end = datetime.fromisoformat(end_raw["date"]).replace(tzinfo=UTC)
        all_day = True
    else:
        return None

    return CalendarEvent(
        id=raw["id"],
        calendar_id=calendar_id,
        title=raw.get("summary", "(no title)"),
        start=start,
        end=end,
        location=raw.get("location"),
        description=raw.get("description"),
        all_day=all_day,
    )


def _fetch_window(
    service: Any,
    calendar_id: str,
    *,
    time_min: datetime,
    time_max: datetime,
    max_results: int = 250,
) -> list[CalendarEvent]:
    """Fetch events from one calendar between time_min and time_max."""
    try:
        result = (
            service.events()
            .list(
                calendarId=calendar_id,
                timeMin=time_min.isoformat(),
                timeMax=time_max.isoformat(),
                maxResults=max_results,
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )
    except HttpError as exc:
        log.error("calendar.fetch_failed", calendar_id=calendar_id, status=exc.status_code)
        raise

    events = [
        evt
        for raw in result.get("items", [])
        if (evt := _parse_event(raw, calendar_id)) is not None
    ]
    log.info("calendar.window_fetched", calendar_id=calendar_id, count=len(events))
    return events


def fetch_calendar_events(settings: Settings, *, days_ahead: int = 7) -> list[CalendarEvent]:
    """Fetch upcoming events across all configured calendars for the next N days."""
    creds = _build_credentials(settings)
    service = build("calendar", "v3", credentials=creds, cache_discovery=False)

    now = datetime.now(UTC)
    end = now + timedelta(days=days_ahead)

    all_events: list[CalendarEvent] = []
    for cal_id in settings.calendar_id_list:
        all_events.extend(_fetch_window(service, cal_id, time_min=now, time_max=end))

    all_events.sort(key=lambda e: e.start)
    log.info("calendar.fetched_upcoming", total=len(all_events), days_ahead=days_ahead)
    return all_events


def fetch_history(settings: Settings, *, months_back: int = 6) -> list[CalendarEvent]:
    """Fetch past events for the preference-profile build.

    Returns events in chronological order. Used only by the monthly profile workflow.
    """
    creds = _build_credentials(settings)
    service = build("calendar", "v3", credentials=creds, cache_discovery=False)

    now = datetime.now(UTC)
    start = now - timedelta(days=months_back * 30)

    all_events: list[CalendarEvent] = []
    for cal_id in settings.calendar_id_list:
        all_events.extend(_fetch_window(service, cal_id, time_min=start, time_max=now))

    all_events.sort(key=lambda e: e.start)
    log.info("calendar.fetched_history", total=len(all_events), months_back=months_back)
    return all_events
