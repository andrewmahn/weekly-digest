"""Claude-powered personalization: monthly profile build + weekly event ranking.

Tiered model selection — Haiku for the monthly summarization task (cheap, large input),
Sonnet for the weekly ranking task (judgment, smaller input). Skips prompt caching: the
5-min / 1-hour cache TTL doesn't survive the 7-day gap between weekly runs.

Both calls use structured outputs (`client.messages.parse`) so the JSON shape is enforced
by Pydantic rather than parsed-and-prayed.
"""

# ruff: noqa: RUF001 — intentional en-dashes inside the prompt templates below

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime

from anthropic import Anthropic
from pydantic import BaseModel, Field

from newsletter.config import Settings
from newsletter.logging_config import get_logger
from newsletter.models import (
    CalendarEvent,
    CandidateEvent,
    Preferences,
    RankedEvent,
)

log = get_logger(__name__)

# ─── Profile build (monthly) ────────────────────────────────────────────────────


class _ProfileResponse(BaseModel):
    music_genres: list[str] = Field(default_factory=list)
    cuisine_likes: list[str] = Field(default_factory=list)
    cuisine_avoids: list[str] = Field(default_factory=list)
    venue_types: list[str] = Field(default_factory=list)
    activity_patterns: list[str] = Field(default_factory=list)
    avoids: list[str] = Field(default_factory=list)
    recent_event_titles: list[str] = Field(default_factory=list)
    notes: str | None = None


_PROFILE_SYSTEM = """You build structured preference profiles from a couple's calendar history.

Output a JSON object describing what they enjoy doing together, based on the events they
actually attended. Be specific and grounded — only include preferences you can point to in
the data. Empty lists are fine.

Also extract the 15 most recent attended event titles verbatim (sanitized — replace any
specific people's names with generic terms like "friend's birthday" or "couple's brunch").
These ground the weekly ranking with concrete signal beyond the high-level profile."""

_PROFILE_USER_TEMPLATE = """Here are calendar events from the past 6 months:

{events}

Build a preference profile. Focus on patterns, not one-offs."""


def _sanitize_event(event: CalendarEvent) -> str:
    parts = [event.start.strftime("%Y-%m-%d %A"), event.title]
    if event.location:
        # Keep neighborhood/venue, drop full addresses
        parts.append(event.location.split(",")[0].strip())
    return " | ".join(parts)


def build_profile(
    history: Iterable[CalendarEvent],
    settings: Settings,
    *,
    client: Anthropic | None = None,
) -> Preferences:
    """Summarize calendar history into a structured preference profile via Claude Haiku."""
    client = client or Anthropic(api_key=settings.anthropic_api_key.get_secret_value())

    event_lines = [_sanitize_event(e) for e in history]
    event_count = len(event_lines)
    if event_count == 0:
        log.warning("profile.empty_history")
        return Preferences(
            built_at=datetime.now(UTC),
            source_event_count=0,
        )

    log.info("profile.build_start", model=settings.claude_profile_model, events=event_count)
    response = client.messages.parse(
        model=settings.claude_profile_model,
        max_tokens=2048,
        system=_PROFILE_SYSTEM,
        messages=[
            {
                "role": "user",
                "content": _PROFILE_USER_TEMPLATE.format(events="\n".join(event_lines)),
            }
        ],
        output_format=_ProfileResponse,
    )
    parsed = response.parsed_output
    if parsed is None:
        raise RuntimeError("Claude profile build returned no parsed output")

    usage = response.usage
    log.info(
        "profile.build_done",
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        recent_titles=len(parsed.recent_event_titles),
    )

    return Preferences(
        music_genres=parsed.music_genres,
        cuisine_likes=parsed.cuisine_likes,
        cuisine_avoids=parsed.cuisine_avoids,
        venue_types=parsed.venue_types,
        activity_patterns=parsed.activity_patterns,
        avoids=parsed.avoids,
        recent_event_titles=parsed.recent_event_titles,
        notes=parsed.notes,
        built_at=datetime.now(UTC),
        source_event_count=event_count,
    )


# ─── Weekly ranking ─────────────────────────────────────────────────────────────


class _RankedItem(BaseModel):
    event_id: str
    rank: int = Field(ge=1)
    reason: str = Field(min_length=10, max_length=200)


class _RankResponse(BaseModel):
    top_events: list[_RankedItem]


_RANKING_SYSTEM = """You're picking the best 5–8 upcoming events in Charlotte for a couple to consider, based on:
1. A structured preference profile built from their calendar history.
2. A list of their most recent attended event titles (concrete grounding).
3. This week's calendar (so you know which nights they're free).
4. A list of candidate events (concerts, sports, theater, etc.).

For each pick:
- Use the EXACT event_id from the candidate list.
- Write one short "why this for you" sentence (under 200 chars) that ties to a SPECIFIC
  signal — a genre from the profile, a recent event title, or a free night in their calendar.
  Vague reasons ("you might like this") are bad. Concrete reasons ("indie show at NoDa,
  similar to the Big Thief show you went to last month") are good.
- Rank starting at 1 for the strongest pick.
- Skip events that conflict with their calendar.
- Skip events that contradict their `avoids` list.
- If fewer than 5 candidates fit, return fewer — don't pad with weak picks."""


def _format_candidates(events: list[CandidateEvent]) -> str:
    lines = []
    for e in events:
        line = f"[{e.id}] {e.short_when} — {e.title}"
        if e.venue:
            line += f" @ {e.venue}"
        if e.subcategory:
            line += f" ({e.subcategory})"
        if e.price_range:
            line += f" — {e.price_range}"
        lines.append(line)
    return "\n".join(lines)


def _format_calendar(events: list[CalendarEvent]) -> str:
    if not events:
        return "(no events scheduled — the whole week is open)"
    return "\n".join(
        f"{e.day_of_week} {e.start.strftime('%b %d')} — {e.title} ({e.time_range})" for e in events
    )


def rank_events(
    candidates: list[CandidateEvent],
    preferences: Preferences,
    upcoming_calendar: list[CalendarEvent],
    settings: Settings,
    *,
    client: Anthropic | None = None,
) -> list[RankedEvent]:
    """Rank candidate events against the cached profile via Claude Sonnet."""
    if not candidates:
        log.info("rank.no_candidates")
        return []

    client = client or Anthropic(api_key=settings.anthropic_api_key.get_secret_value())

    user_content = f"""## Preference profile

{preferences.model_dump_json(indent=2, exclude={"built_at", "source_event_count"})}

## This week's calendar

{_format_calendar(upcoming_calendar)}

## Candidate events ({len(candidates)})

{_format_candidates(candidates)}

Pick the top 5–8 events for this couple. Use exact event_ids from the list above."""

    log.info(
        "rank.start",
        model=settings.claude_ranking_model,
        candidates=len(candidates),
        calendar_events=len(upcoming_calendar),
    )
    # Sonnet 4.6 defaults to effort: "high" + adaptive thinking. For a structured ranking
    # task (50 candidates → top 5-8 with one-sentence reasons) that's massive overspend —
    # one default-config call cost ~$0.70-1.50 in the first dry-run. Explicit low effort
    # and disabled thinking keep this under $0.10/call without measurable quality loss.
    response = client.messages.parse(
        model=settings.claude_ranking_model,
        max_tokens=2048,
        thinking={"type": "disabled"},
        output_config={"effort": "low"},
        system=_RANKING_SYSTEM,
        messages=[{"role": "user", "content": user_content}],
        output_format=_RankResponse,
    )
    parsed = response.parsed_output
    if parsed is None:
        raise RuntimeError("Claude ranking returned no parsed output")

    usage = response.usage
    log.info(
        "rank.done",
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        picks=len(parsed.top_events),
    )

    candidates_by_id = {c.id: c for c in candidates}
    ranked: list[RankedEvent] = []
    for item in sorted(parsed.top_events, key=lambda i: i.rank):
        event = candidates_by_id.get(item.event_id)
        if event is None:
            log.warning("rank.unknown_event_id", event_id=item.event_id)
            continue
        ranked.append(RankedEvent(event=event, reason=item.reason, rank=item.rank))

    return ranked
