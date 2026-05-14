"""CLI entrypoint for weekly-digest.

Two modes:
- `--profile`: monthly job. Reads ~6 months of calendar history, builds a preference profile
  via Claude Haiku, writes it to `data/preferences.json`. Run via the monthly GH Actions
  workflow; the resulting file is then stored in the GH Actions cache.
- `--weekly`: weekly job. Fetches all sources, ranks events via Claude Sonnet, renders the
  newsletter, sends via Resend (or writes to disk with `--dry-run`).

Per-source resilience: a failing source renders as "data unavailable" in the relevant
section, but the rest of the newsletter still ships. Hard failures (auth, no profile
on disk for a weekly run, no Resend credentials) raise.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, TypeVar

from newsletter.config import PREFERENCES_PATH, Settings, load_settings
from newsletter.logging_config import configure_logging, get_logger
from newsletter.models import (
    CalendarEvent,
    CandidateEvent,
    DealPick,
    NewsletterContext,
    PersonalizationResult,
    Preferences,
    WeatherForecast,
)
from newsletter.personalize import build_profile, personalize_newsletter
from newsletter.render import render_newsletter, write_to_disk
from newsletter.send import send_email
from newsletter.sources.calendar import fetch_calendar_events, fetch_history
from newsletter.sources.deals import fetch_deals
from newsletter.sources.songkick import fetch_songkick_events
from newsletter.sources.ticketmaster import fetch_ticketmaster_events
from newsletter.sources.weather import fetch_weather

log = get_logger(__name__)


def _load_preferences() -> Preferences | None:
    """Load the cached preference profile, or None if the cache is cold."""
    if not PREFERENCES_PATH.exists():
        log.warning("preferences.cold_cache", path=str(PREFERENCES_PATH))
        return None
    try:
        return Preferences.model_validate_json(PREFERENCES_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        log.error("preferences.load_failed", error=str(exc))
        return None


def _save_preferences(prefs: Preferences) -> None:
    PREFERENCES_PATH.parent.mkdir(parents=True, exist_ok=True)
    PREFERENCES_PATH.write_text(prefs.model_dump_json(indent=2), encoding="utf-8")
    log.info("preferences.saved", path=str(PREFERENCES_PATH))


def run_profile(settings: Settings) -> int:
    """Monthly profile-build entry point. Returns shell exit code."""
    log.info("profile.run_start")
    history = fetch_history(settings, months_back=6)
    if not history:
        log.warning("profile.empty_history_skip")
        return 0
    prefs = build_profile(history, settings)
    _save_preferences(prefs)
    log.info(
        "profile.run_done",
        events=prefs.source_event_count,
        recent_titles=len(prefs.recent_event_titles),
    )
    return 0


# ─── Weekly run helpers ─────────────────────────────────────────────────────────


_T = TypeVar("_T")


def _safe(
    source_name: str,
    errors: dict[str, str],
    fn: Callable[..., _T],
    *args: Any,
    **kwargs: Any,
) -> _T | None:
    """Wrap a source fetch so a failure doesn't kill the run.

    Returns the function's result on success, or None on failure (with the failure
    recorded in `errors` so the template can surface it).
    """
    try:
        return fn(*args, **kwargs)
    except Exception as exc:
        log.error("source.failed", source=source_name, error=str(exc))
        errors[source_name] = type(exc).__name__
        return None


# Lead-time thresholds. Same-week shows are too late to plan around comfortably;
# mainstream/expensive shows ($40+ ticket floor) need 3+ weeks so tickets don't
# sell out (or balloon on resale) by the time the reader sees the newsletter.
_MIN_LEAD_DAYS = 7
_MAINSTREAM_MIN_LEAD_DAYS = 21
_MAINSTREAM_PRICE_FLOOR = 40.0


def _apply_lead_time_filter(
    events: list[CandidateEvent], *, now: datetime
) -> list[CandidateEvent]:
    """Drop events that don't give enough buying lead time.

    - Always drop events <7 days out (the "no same-week concerts" rule).
    - Additionally drop events <21 days out whose min ticket price is >=$40
      (these are mainstream shows with sell-out / resale-markup risk).
    """
    # Ticketmaster events carry naive (local) datetimes; Songkick carries aware ones.
    # For days-precision lead time, TZ doesn't matter — strip both to the same frame.
    now_naive = now.replace(tzinfo=None)

    kept: list[CandidateEvent] = []
    dropped_same_week = 0
    dropped_mainstream = 0
    for event in events:
        event_start = event.start.replace(tzinfo=None)
        days_out = (event_start - now_naive).days
        if days_out < _MIN_LEAD_DAYS:
            dropped_same_week += 1
            continue
        if (
            event.min_price is not None
            and event.min_price >= _MAINSTREAM_PRICE_FLOOR
            and days_out < _MAINSTREAM_MIN_LEAD_DAYS
        ):
            dropped_mainstream += 1
            continue
        kept.append(event)
    log.info(
        "events.lead_time_filtered",
        kept=len(kept),
        dropped_same_week=dropped_same_week,
        dropped_mainstream=dropped_mainstream,
    )
    return kept


def run_weekly(settings: Settings, *, dry_run: bool, recipients: list[str] | None) -> int:
    """Weekly newsletter run. Returns shell exit code."""
    log.info("weekly.run_start", dry_run=dry_run)
    errors: dict[str, str] = {}

    today = date.today()
    week_start = today
    week_end = today + timedelta(days=6)

    calendar_events: list[CalendarEvent] = (
        _safe("calendar", errors, fetch_calendar_events, settings, days_ahead=7) or []
    )
    weather: WeatherForecast | None = _safe(
        "weather", errors, fetch_weather, settings, start=week_start
    )

    tm_events: list[CandidateEvent] = (
        _safe("ticketmaster", errors, fetch_ticketmaster_events, settings, days_ahead=60) or []
    )
    sk_events: list[CandidateEvent] = (
        _safe("songkick", errors, fetch_songkick_events, settings, days_ahead=60) or []
    )
    candidates = _apply_lead_time_filter(tm_events + sk_events, now=datetime.now(UTC))
    log.info("weekly.candidates", ticketmaster=len(tm_events), songkick=len(sk_events))

    prefs = _load_preferences()
    if prefs is None:
        # Cold-start fallback: build the profile inline. Still ships the newsletter.
        log.info("weekly.cold_start_profile_build")
        history = _safe("calendar_history", errors, fetch_history, settings, months_back=6) or []
        if history:
            prefs = build_profile(history, settings)
            _save_preferences(prefs)
        else:
            prefs = Preferences(built_at=datetime.now(UTC), source_event_count=0)

    raw_deals: list[DealPick] = (
        _safe("deals", errors, fetch_deals, settings, week_start=week_start, week_end=week_end)
        or []
    )

    # One Sonnet call ranks events, filters deals by demographic fit, and writes the
    # editor's note + section intros. Skipped if there's nothing to rank or filter.
    personalization: PersonalizationResult = (
        _safe(
            "personalize",
            errors,
            personalize_newsletter,
            candidates,
            raw_deals,
            prefs,
            calendar_events,
            settings,
        )
        or PersonalizationResult()
    )

    context = NewsletterContext(
        generated_at=datetime.now(UTC),
        week_start=week_start,
        week_end=week_end,
        city_name=f"{settings.city_name}, {settings.city_state}",
        calendar_events=calendar_events,
        weather=weather,
        ranked_events=personalization.ranked_events,
        deals=personalization.kept_deals,
        commentary=personalization.commentary,
        section_errors=errors,
    )

    html = render_newsletter(context)

    if dry_run:
        out_path = (
            Path(__file__).parent.parent / "out" / f"newsletter-{week_start.isoformat()}.html"
        )
        write_to_disk(html, out_path)
        log.info("weekly.dry_run_complete", path=str(out_path))
        return 0

    subject = f"Weekly Digest — {week_start.strftime('%B %d')}"
    send_email(settings, subject=subject, html=html, recipients=recipients)
    log.info("weekly.run_done", sections_with_errors=list(errors.keys()))
    return 0


# ─── CLI ────────────────────────────────────────────────────────────────────────


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="newsletter", description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--weekly", action="store_true", help="Build and send the weekly newsletter")
    mode.add_argument("--profile", action="store_true", help="Build the monthly preference profile")
    parser.add_argument(
        "--dry-run", action="store_true", help="Render to disk instead of sending email"
    )
    parser.add_argument(
        "--to",
        action="append",
        help="Override recipient email(s). Can be specified multiple times. Defaults to NEWSLETTER_TO_EMAILS.",
    )
    parser.add_argument("--log-level", default="INFO", help="Logging level (default: INFO)")
    return parser


def cli() -> None:
    args = _build_parser().parse_args()
    configure_logging(args.log_level)

    try:
        settings = load_settings()
    except Exception as exc:
        sys.stderr.write(f"Failed to load settings: {exc}\n")
        sys.exit(2)

    if args.profile:
        sys.exit(run_profile(settings))
    else:
        sys.exit(run_weekly(settings, dry_run=args.dry_run, recipients=args.to))


if __name__ == "__main__":
    cli()
