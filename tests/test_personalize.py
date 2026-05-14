"""Test the personalization layer with a stubbed Anthropic client.

These tests verify the contract — given a known response shape, do build_profile and
rank_events produce the right typed output? We don't exercise the real API.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from newsletter.config import Settings
from newsletter.models import CalendarEvent, CandidateEvent, Preferences
from newsletter.personalize import (
    _ProfileResponse,
    _RankedItem,
    _RankResponse,
    build_profile,
    rank_events,
)


class _StubMessages:
    """Mimics client.messages — returns a canned parsed_output."""

    def __init__(self, parsed_output: Any) -> None:
        self._parsed_output = parsed_output

    def parse(self, **kwargs: Any) -> Any:
        return SimpleNamespace(
            parsed_output=self._parsed_output,
            usage=SimpleNamespace(input_tokens=1000, output_tokens=200),
        )


class _StubClient:
    def __init__(self, parsed_output: Any) -> None:
        self.messages = _StubMessages(parsed_output)


def test_build_profile_assembles_preferences(
    settings: Settings, sample_calendar_events: list[CalendarEvent]
) -> None:
    stub_response = _ProfileResponse(
        music_genres=["indie folk"],
        cuisine_likes=["southern"],
        recent_event_titles=["Brunch at Optimist Hall"],
    )
    client = _StubClient(stub_response)

    prefs = build_profile(sample_calendar_events, settings, client=client)  # type: ignore[arg-type]

    assert isinstance(prefs, Preferences)
    assert prefs.music_genres == ["indie folk"]
    assert prefs.cuisine_likes == ["southern"]
    assert prefs.recent_event_titles == ["Brunch at Optimist Hall"]
    assert prefs.source_event_count == len(sample_calendar_events)


def test_build_profile_empty_history_short_circuits(settings: Settings) -> None:
    # No client call should happen — passing a deliberately-broken client proves it.
    class _ExplodingClient:
        @property
        def messages(self) -> Any:
            raise AssertionError("client should not be called for empty history")

    prefs = build_profile([], settings, client=_ExplodingClient())  # type: ignore[arg-type]
    assert prefs.source_event_count == 0
    assert prefs.music_genres == []


def test_rank_events_orders_by_rank_and_attaches_reasons(
    settings: Settings,
    sample_candidates: list[CandidateEvent],
    sample_preferences: Preferences,
) -> None:
    stub_response = _RankResponse(
        top_events=[
            _RankedItem(
                event_id="tm2", rank=2, reason="Hornets game — your free Wednesday evening."
            ),
            _RankedItem(
                event_id="tm1",
                rank=1,
                reason="Big Thief at The Fillmore — matches your indie folk preference.",
            ),
        ]
    )
    client = _StubClient(stub_response)

    ranked = rank_events(sample_candidates, sample_preferences, [], settings, client=client)  # type: ignore[arg-type]

    assert len(ranked) == 2
    assert ranked[0].rank == 1
    assert ranked[0].event.id == "tm1"
    assert "indie folk" in ranked[0].reason
    assert ranked[1].rank == 2
    assert ranked[1].event.id == "tm2"


def test_rank_events_drops_unknown_event_ids(
    settings: Settings,
    sample_candidates: list[CandidateEvent],
    sample_preferences: Preferences,
) -> None:
    stub_response = _RankResponse(
        top_events=[
            _RankedItem(
                event_id="tm1", rank=1, reason="Great match for your indie folk preference."
            ),
            _RankedItem(
                event_id="hallucinated-id",
                rank=2,
                reason="An event the model invented out of thin air.",
            ),
        ]
    )
    client = _StubClient(stub_response)

    ranked = rank_events(sample_candidates, sample_preferences, [], settings, client=client)  # type: ignore[arg-type]

    assert len(ranked) == 1
    assert ranked[0].event.id == "tm1"


def test_rank_events_no_candidates_skips_api(
    settings: Settings, sample_preferences: Preferences
) -> None:
    class _ExplodingClient:
        @property
        def messages(self) -> Any:
            raise AssertionError("client should not be called when there are no candidates")

    ranked = rank_events([], sample_preferences, [], settings, client=_ExplodingClient())  # type: ignore[arg-type]
    assert ranked == []
