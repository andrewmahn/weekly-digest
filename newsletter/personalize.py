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
    DealPick,
    NewsletterCommentary,
    PersonalizationResult,
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


# ─── Weekly personalization (unified call) ──────────────────────────────────────
#
# One Sonnet 4.6 call (effort: low, thinking: off) that combines:
#   1. Event ranking with a concrete-signal-or-reject rule.
#   2. Deal filtering for demographic fit (drop senior/military/kids-only items).
#   3. Editorial commentary (editor's note + section intros).
#
# Earlier versions did only #1. Folding #2 and #3 into the same call adds ~$0.02
# to the run (~5400 input / 800 output tokens on Sonnet 4.6 with the low/off
# controls) and eliminates ad-hoc post-hoc filtering scattered across the codebase.


class _RankedItem(BaseModel):
    event_id: str
    # Round-trip the title back so we can detect Claude pairing event_id with the
    # wrong reason — Ticketmaster IDs are opaque 16-char strings and structured-output
    # drift sometimes copies an ID from one row but writes a reason about another.
    event_title: str
    rank: int = Field(ge=1)
    reason: str = Field(min_length=10, max_length=240)


class _PersonalizationResponse(BaseModel):
    editor_note: str = Field(default="", max_length=600)
    picks_intro: str = Field(default="", max_length=400)
    deals_intro: str = Field(default="", max_length=400)
    top_events: list[_RankedItem] = Field(default_factory=list)
    kept_deal_indices: list[int] = Field(default_factory=list)


_PERSONALIZE_SYSTEM = """You're the editor of a couple's weekly newsletter for Charlotte, NC. Each week you produce:
1. Ranked event picks with personalized reasons.
2. A filtered list of deals/happy hours.
3. Brief editorial commentary.

You're given:
- A preference profile built from their calendar history (genres, cuisines, venues, recent attended titles).
- This week's calendar (which evenings are free).
- Candidate upcoming events from Ticketmaster/Songkick.
- Candidate deals from a Charlotte local-events blog.

## RANKING RULES (strict)

For each pick:
- Use the EXACT event_id from the candidate list AND copy ONLY the event's title (the part before " @ ") into the event_title field — do NOT include venue, date, or price. Both fields must come from the SAME row — never mix an event_id from one row with a title or reason from another.
- Every reason MUST cite a SPECIFIC signal verbatim:
  • a music genre from the profile (e.g. "indie rock"), OR
  • a cuisine/venue type from the profile (e.g. "oyster bar", "concert venues"), OR
  • a specific event title from recent_event_titles.
- Generic ties are FORBIDDEN. Do NOT write reasons like:
  "great date night option", "fits your live music preference",
  "perfect for a free evening", "love of live music events".
- If you cannot cite a specific signal, do NOT include the pick.
- Rank starts at 1 for the strongest pick. Return 0–8 picks. Fewer-but-stronger > padded.
- Skip events that conflict with their calendar.
- Skip events that contradict their `avoids` list.

## DEAL FILTERING RULES

For each deal in the candidate list (0-indexed), decide keep or drop. Output the INDICES of deals to keep.
DROP deals that target a demographic this couple is not in:
  • senior-only / AARP-only / 55+
  • military / veteran-only discounts
  • kids-only / family-with-young-children / school-age
  • student-only discounts
DROP deals that are clearly mass aggregators or content marketing (not actual deals).
KEEP deals that plausibly fit a thirty-something couple: happy hours, restaurant specials,
free local events, festivals, markets, concerts under $30, anything that matches their profile.

## EDITORIAL COMMENTARY RULES

Write three short pieces of editorial copy:
- editor_note: 2–3 sentences setting the tone for the whole week. Mention the strongest pick by name. Be concrete — not "have a great week!" filler.
- picks_intro: 1–2 sentences introducing the "Picks for you" section. Reference a specific pattern in the picks (e.g. "Indie rock has the strongest run this week" or "Three Friday-night options if you want to be social").
- deals_intro: 1–2 sentences introducing the "Happy hours & deals" section. Reference a specific kept deal or theme.

If there are zero ranked picks, picks_intro can be empty. Same for deals_intro."""


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


def _format_deals(deals: list[DealPick]) -> str:
    if not deals:
        return "(no deals)"
    lines = []
    for idx, d in enumerate(deals):
        lines.append(f"[{idx}] ({d.deal_type.value}) {d.title}")
        lines.append(f"    {d.description[:200]}")
    return "\n".join(lines)


def personalize_newsletter(
    candidates: list[CandidateEvent],
    deals: list[DealPick],
    preferences: Preferences,
    upcoming_calendar: list[CalendarEvent],
    settings: Settings,
    *,
    client: Anthropic | None = None,
) -> PersonalizationResult:
    """Rank events, filter deals, and write editorial commentary in one Sonnet call.

    Returns a PersonalizationResult. If there are no candidates AND no deals, no API
    call is made and an empty result is returned.
    """
    if not candidates and not deals:
        log.info("personalize.nothing_to_do")
        return PersonalizationResult()

    client = client or Anthropic(api_key=settings.anthropic_api_key.get_secret_value())

    user_content = f"""## Preference profile

{preferences.model_dump_json(indent=2, exclude={"built_at", "source_event_count"})}

## This week's calendar

{_format_calendar(upcoming_calendar)}

## Candidate events ({len(candidates)})

{_format_candidates(candidates)}

## Candidate deals ({len(deals)})

{_format_deals(deals)}

Produce ranked picks (concrete signal required), kept-deal indices, and the three pieces of editorial copy."""

    log.info(
        "personalize.start",
        model=settings.claude_ranking_model,
        candidates=len(candidates),
        deals=len(deals),
        calendar_events=len(upcoming_calendar),
    )
    # Sonnet 4.6 defaults to effort: "high" + adaptive thinking. For this structured task
    # — rank N candidates with a strict signal rule, output filter indices, write three
    # short blurbs — high-effort thinking is massive overspend and produced no measurable
    # quality lift in early dry-runs. Low effort + thinking off keeps the call ~$0.03/run.
    response = client.messages.parse(
        model=settings.claude_ranking_model,
        max_tokens=3072,
        thinking={"type": "disabled"},
        output_config={"effort": "low"},
        system=_PERSONALIZE_SYSTEM,
        messages=[{"role": "user", "content": user_content}],
        output_format=_PersonalizationResponse,
    )
    parsed = response.parsed_output
    if parsed is None:
        raise RuntimeError("Claude personalization returned no parsed output")

    usage = response.usage
    log.info(
        "personalize.done",
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        picks=len(parsed.top_events),
        kept_deals=len(parsed.kept_deal_indices),
    )

    candidates_by_id = {c.id: c for c in candidates}
    ranked: list[RankedEvent] = []
    for item in sorted(parsed.top_events, key=lambda i: i.rank):
        event = candidates_by_id.get(item.event_id)
        if event is None:
            log.warning("personalize.unknown_event_id", event_id=item.event_id)
            continue
        # Cross-check title to catch structured-output drift where Claude pairs an
        # event_id from one row with a reason about a different event. Use a
        # prefix-tolerant compare — Claude sometimes appends "@ venue" to the title
        # despite the prompt, and real drift always involves entirely different acts
        # whose titles share no leading prefix. Require >=8 chars of overlap to be
        # specific enough.
        claimed = " ".join(item.event_title.strip().lower().split())
        actual = " ".join(event.title.strip().lower().split())
        shorter, longer = sorted([claimed, actual], key=len)
        if not (shorter == longer or (len(shorter) >= 8 and longer.startswith(shorter))):
            log.warning(
                "personalize.title_mismatch_skipped",
                event_id=item.event_id,
                actual_title=event.title,
                claimed_title=item.event_title,
            )
            continue
        ranked.append(RankedEvent(event=event, reason=item.reason, rank=item.rank))

    kept_deals: list[DealPick] = []
    for idx in parsed.kept_deal_indices:
        if 0 <= idx < len(deals):
            kept_deals.append(deals[idx])
        else:
            log.warning("personalize.deal_index_out_of_range", index=idx, total=len(deals))

    return PersonalizationResult(
        ranked_events=ranked,
        kept_deals=kept_deals,
        commentary=NewsletterCommentary(
            editor_note=parsed.editor_note.strip(),
            picks_intro=parsed.picks_intro.strip(),
            deals_intro=parsed.deals_intro.strip(),
        ),
    )
