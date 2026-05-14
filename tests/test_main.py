"""Tests for orchestration helpers in newsletter.main."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from newsletter.main import _apply_lead_time_filter
from newsletter.models import CandidateEvent, EventSource

NOW = datetime(2026, 5, 17, 12, 0, tzinfo=UTC)


def _event(days_out: int, *, min_price: float | None, naive: bool = False) -> CandidateEvent:
    """Build a CandidateEvent. naive=True mirrors the Ticketmaster parser's behavior."""
    start = NOW + timedelta(days=days_out)
    if naive:
        start = start.replace(tzinfo=None)
    return CandidateEvent(
        id=f"e-{days_out}-{min_price}-{naive}",
        source=EventSource.TICKETMASTER,
        title=f"Show in {days_out} days",
        start=start,
        url="https://www.ticketmaster.com/event/x",
        min_price=min_price,
    )


def test_lead_time_filter_drops_same_week_regardless_of_price() -> None:
    events = [
        _event(2, min_price=15),  # niche, this week — drop
        _event(5, min_price=80),  # mainstream, this week — drop
        _event(8, min_price=15),  # niche, next week — keep
    ]
    kept = _apply_lead_time_filter(events, now=NOW)
    assert [e.start - NOW for e in kept] == [timedelta(days=8)]


def test_lead_time_filter_gates_mainstream_behind_three_weeks() -> None:
    events = [
        _event(10, min_price=80),  # mainstream, 10 days — drop
        _event(14, min_price=80),  # mainstream, 14 days — drop
        _event(21, min_price=80),  # mainstream, 21 days — keep (boundary)
        _event(30, min_price=120),  # mainstream, well in advance — keep
    ]
    kept = _apply_lead_time_filter(events, now=NOW)
    days = sorted((e.start - NOW).days for e in kept)
    assert days == [21, 30]


def test_lead_time_filter_keeps_niche_shows_in_short_window() -> None:
    events = [
        _event(10, min_price=15),  # niche, 10 days — keep
        _event(10, min_price=39.99),  # just under floor — keep
    ]
    kept = _apply_lead_time_filter(events, now=NOW)
    assert len(kept) == 2


def test_lead_time_filter_treats_missing_price_as_niche() -> None:
    """Songkick doesn't expose price; those events should pass the niche rule."""
    events = [
        _event(8, min_price=None),  # 8 days, no price — keep (just past same-week)
        _event(3, min_price=None),  # 3 days, no price — drop (still same-week)
    ]
    kept = _apply_lead_time_filter(events, now=NOW)
    assert len(kept) == 1
    assert (kept[0].start - NOW).days == 8


def test_lead_time_filter_handles_naive_ticketmaster_starts() -> None:
    """Ticketmaster events arrive with tz-naive starts; comparison must not crash."""
    events = [
        _event(30, min_price=50, naive=True),
        _event(3, min_price=50, naive=True),
    ]
    kept = _apply_lead_time_filter(events, now=NOW)
    assert len(kept) == 1
    naive_now = NOW.replace(tzinfo=None)
    assert (kept[0].start - naive_now).days == 30
