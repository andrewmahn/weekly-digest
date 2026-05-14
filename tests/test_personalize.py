"""Test the personalization layer with a stubbed Anthropic client.

These tests verify the contract — given a known response shape, do build_profile and
personalize_newsletter produce the right typed output? We don't exercise the real API.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from newsletter.config import Settings
from newsletter.models import (
    CalendarEvent,
    CandidateEvent,
    DealPick,
    Preferences,
)
from newsletter.personalize import (
    _PersonalizationResponse,
    _ProfileResponse,
    _RankedItem,
    build_profile,
    personalize_newsletter,
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
    class _ExplodingClient:
        @property
        def messages(self) -> Any:
            raise AssertionError("client should not be called for empty history")

    prefs = build_profile([], settings, client=_ExplodingClient())  # type: ignore[arg-type]
    assert prefs.source_event_count == 0
    assert prefs.music_genres == []


def test_personalize_orders_picks_filters_deals_and_carries_commentary(
    settings: Settings,
    sample_candidates: list[CandidateEvent],
    sample_preferences: Preferences,
    sample_deals: list[DealPick],
) -> None:
    stub_response = _PersonalizationResponse(
        editor_note="Quiet week — Big Thief at The Fillmore is the standout.",
        picks_intro="Indie folk has the strongest run this week.",
        deals_intro="Tuesday-night oysters if you want a low-key date.",
        top_events=[
            _RankedItem(
                event_id="tm2",
                event_title="Hornets vs Lakers",
                rank=2,
                reason="Hornets game — your indie folk Wednesday is open.",
            ),
            _RankedItem(
                event_id="tm1",
                event_title="Big Thief at The Fillmore",
                rank=1,
                reason="Big Thief at The Fillmore — matches indie folk from your profile.",
            ),
        ],
        kept_deal_indices=[0],  # keep oysters, drop the movie
    )
    client = _StubClient(stub_response)

    result = personalize_newsletter(
        sample_candidates,
        sample_deals,
        sample_preferences,
        [],
        settings,
        client=client,  # type: ignore[arg-type]
    )

    # Ranked events are sorted by rank, with reasons attached.
    assert len(result.ranked_events) == 2
    assert result.ranked_events[0].rank == 1
    assert result.ranked_events[0].event.id == "tm1"
    assert "indie folk" in result.ranked_events[0].reason
    assert result.ranked_events[1].rank == 2

    # Deal indices are honored.
    assert len(result.kept_deals) == 1
    assert result.kept_deals[0].title == "Half-price oysters"

    # Commentary is carried through.
    assert "Big Thief" in result.commentary.editor_note
    assert result.commentary.picks_intro.startswith("Indie folk")
    assert result.commentary.deals_intro.startswith("Tuesday")


def test_personalize_drops_unknown_event_ids(
    settings: Settings,
    sample_candidates: list[CandidateEvent],
    sample_preferences: Preferences,
) -> None:
    stub_response = _PersonalizationResponse(
        top_events=[
            _RankedItem(
                event_id="tm1",
                event_title="Big Thief at The Fillmore",
                rank=1,
                reason="Indie folk match from your profile.",
            ),
            _RankedItem(
                event_id="hallucinated-id",
                event_title="A made-up event",
                rank=2,
                reason="An event the model invented out of thin air.",
            ),
        ],
    )
    client = _StubClient(stub_response)

    result = personalize_newsletter(
        sample_candidates,
        [],
        sample_preferences,
        [],
        settings,
        client=client,  # type: ignore[arg-type]
    )

    assert len(result.ranked_events) == 1
    assert result.ranked_events[0].event.id == "tm1"


def test_personalize_drops_picks_with_title_drift(
    settings: Settings,
    sample_candidates: list[CandidateEvent],
    sample_preferences: Preferences,
) -> None:
    """If Claude pairs an event_id with a reason describing a different event,
    the title round-trip catches it and the pick is dropped."""
    stub_response = _PersonalizationResponse(
        top_events=[
            _RankedItem(
                event_id="tm1",
                event_title="Big Thief at The Fillmore",
                rank=1,
                reason="Indie folk match from your profile.",
            ),
            _RankedItem(
                event_id="tm2",  # this id is Hornets vs Lakers
                event_title="The Mountain Goats",  # but Claude wrote a Mountain Goats title
                rank=2,
                reason="The Mountain Goats at Neighborhood Theatre — indie rock match.",
            ),
        ],
    )
    client = _StubClient(stub_response)

    result = personalize_newsletter(
        sample_candidates, [], sample_preferences, [], settings, client=client  # type: ignore[arg-type]
    )

    assert len(result.ranked_events) == 1
    assert result.ranked_events[0].event.id == "tm1"


def test_personalize_accepts_venue_suffixed_titles(
    settings: Settings,
    sample_candidates: list[CandidateEvent],
    sample_preferences: Preferences,
) -> None:
    """Claude sometimes appends ' @ venue' to the title — the same event, not drift."""
    stub_response = _PersonalizationResponse(
        top_events=[
            _RankedItem(
                event_id="tm1",
                # Real Big Thief event, but Claude added the venue
                event_title="Big Thief at The Fillmore @ The Fillmore Charlotte",
                rank=1,
                reason="Indie folk match from your profile.",
            ),
        ],
    )
    client = _StubClient(stub_response)

    result = personalize_newsletter(
        sample_candidates, [], sample_preferences, [], settings, client=client  # type: ignore[arg-type]
    )

    assert len(result.ranked_events) == 1
    assert result.ranked_events[0].event.id == "tm1"


def test_personalize_ignores_out_of_range_deal_indices(
    settings: Settings,
    sample_preferences: Preferences,
    sample_deals: list[DealPick],
) -> None:
    stub_response = _PersonalizationResponse(
        kept_deal_indices=[0, 5, -1],  # 5 and -1 are bogus
    )
    client = _StubClient(stub_response)

    result = personalize_newsletter(
        [], sample_deals, sample_preferences, [], settings, client=client  # type: ignore[arg-type]
    )

    assert len(result.kept_deals) == 1
    assert result.kept_deals[0] is sample_deals[0]


def test_personalize_short_circuits_when_nothing_to_do(
    settings: Settings, sample_preferences: Preferences
) -> None:
    class _ExplodingClient:
        @property
        def messages(self) -> Any:
            raise AssertionError("client should not be called when there are no candidates or deals")

    result = personalize_newsletter(
        [], [], sample_preferences, [], settings, client=_ExplodingClient()  # type: ignore[arg-type]
    )
    assert result.ranked_events == []
    assert result.kept_deals == []
    assert result.commentary.editor_note == ""
