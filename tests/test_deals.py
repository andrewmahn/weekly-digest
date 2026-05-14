"""Test the deals source with a stubbed Anthropic client.

The deals source delegates to Claude's web_search tool, which we can't exercise
without a real API call. These tests verify the contract: given a typed parsed
response, do we surface the right DealPick list, and do we handle pause_turn and
empty parses gracefully?
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from typing import Any

from newsletter.config import Settings
from newsletter.models import DealPick, DealType
from newsletter.sources.deals import _DealsResponse, fetch_deals


class _StubMessages:
    """Mimic client.messages.parse with a configurable response sequence."""

    def __init__(self, responses: list[Any]) -> None:
        self._responses = list(responses)
        self.call_count = 0

    def parse(self, **kwargs: Any) -> Any:
        self.call_count += 1
        return self._responses.pop(0)


class _StubClient:
    def __init__(self, responses: list[Any]) -> None:
        self.messages = _StubMessages(responses)


def _ok_response(parsed: Any, stop_reason: str = "end_turn") -> SimpleNamespace:
    return SimpleNamespace(
        parsed_output=parsed,
        stop_reason=stop_reason,
        content=[],
        usage=SimpleNamespace(input_tokens=1500, output_tokens=400),
    )


def _sample_deal_pick() -> DealPick:
    return DealPick(
        title="Half-price oysters",
        description="Tuesday happy hour at this NoDa seafood spot — local oysters cut in half from 5 to 7pm.",
        venue="The Stanley",
        neighborhood="Elizabeth",
        deal_type=DealType.HAPPY_HOUR,
        when="Tuesdays 5–7pm",  # noqa: RUF001 — intentional en-dash for display
        source_url="https://example.com/the-stanley-happy-hour",
    )


def test_fetch_deals_returns_parsed_picks(settings: Settings) -> None:
    deal = _sample_deal_pick()
    client = _StubClient([_ok_response(_DealsResponse(deals=[deal]))])

    picks = fetch_deals(
        settings,
        week_start=date(2026, 5, 17),
        week_end=date(2026, 5, 23),
        client=client,  # type: ignore[arg-type]
    )

    assert len(picks) == 1
    assert picks[0].title == "Half-price oysters"
    assert picks[0].deal_type == DealType.HAPPY_HOUR
    assert client.messages.call_count == 1


def test_fetch_deals_resumes_on_pause_turn(settings: Settings) -> None:
    deal = _sample_deal_pick()
    # First response pauses (server-side loop hit cap); second completes.
    client = _StubClient(
        [
            _ok_response(None, stop_reason="pause_turn"),
            _ok_response(_DealsResponse(deals=[deal]), stop_reason="end_turn"),
        ]
    )

    picks = fetch_deals(
        settings,
        week_start=date(2026, 5, 17),
        week_end=date(2026, 5, 23),
        client=client,  # type: ignore[arg-type]
    )

    assert len(picks) == 1
    assert client.messages.call_count == 2


def test_fetch_deals_returns_empty_when_no_parsed_output(settings: Settings) -> None:
    client = _StubClient([_ok_response(None)])

    picks = fetch_deals(
        settings,
        week_start=date(2026, 5, 17),
        week_end=date(2026, 5, 23),
        client=client,  # type: ignore[arg-type]
    )

    assert picks == []


def test_fetch_deals_handles_empty_deals_list(settings: Settings) -> None:
    client = _StubClient([_ok_response(_DealsResponse(deals=[]))])

    picks = fetch_deals(
        settings,
        week_start=date(2026, 5, 17),
        week_end=date(2026, 5, 23),
        client=client,  # type: ignore[arg-type]
    )

    assert picks == []
