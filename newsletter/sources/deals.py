"""Deals source — Claude with the web_search server-side tool.

There is no clean public API for "happy hours and restaurant deals in Charlotte" — the
ecosystem is a patchwork of restaurant websites, local-news blog posts, and Instagram. So
this source delegates discovery to Claude with the web_search tool enabled. Once a week
Claude searches for current Charlotte happy hours / specials / cheap events, filters out
stale or off-topic results, and returns a structured list of picks with source URLs for
attribution.

Why this is OK to run weekly:
- One server-side search call, ~$0.01 per run.
- 5-min / 1-hour cache TTL doesn't survive the 7-day gap between newsletter runs, so we
  skip prompt caching.
- A failed deals call is non-fatal — `_safe` in main.py records the error and the
  newsletter ships without the deals section.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from anthropic import Anthropic
from anthropic.types import MessageParam
from pydantic import BaseModel, Field

from newsletter.config import Settings
from newsletter.logging_config import get_logger
from newsletter.models import DealPick

log = get_logger(__name__)

# The 20260209 web_search version (with dynamic filtering) isn't yet in the SDK's
# narrowly-typed ToolParam union, so we annotate as Any to avoid a list-item type error.
_WEB_SEARCH_TOOL: Any = {"type": "web_search_20260209", "name": "web_search"}

_DEALS_SYSTEM = """You research happy hours, restaurant deals, and free/cheap local events \
for a couple's weekly newsletter in Charlotte, NC.

Use the web_search tool to find CURRENT information. Search the open web, prioritizing:
- Restaurant happy hours (e.g. "Tuesdays 5-7pm half-price oysters at The Stanley")
- Prix fixe or restaurant-week-style specials
- Free or cheap (<$20) local events: outdoor movies, gallery crawls, festivals, markets

Strict requirements for every pick:
1. Charlotte, NC specifically — not Charlottesville VA, not Port Charlotte FL, not any other city.
2. Active in the coming 7 days from the date in the user message. Be skeptical of any page that mentions a past year's event or appears outdated — skip it.
3. Each pick MUST include a specific venue name. "Various restaurants" is not acceptable.
4. Each pick MUST include a real source URL Claude actually retrieved (no fabricated links).

Output 3-8 picks. Quality over quantity — three solid happy hours is better than eight \
vague specials. If you cannot find enough current information after a few searches, return \
fewer picks rather than padding with low-confidence items."""


_DEALS_USER_TEMPLATE = """The newsletter covers {week_start} through {week_end}.

Find 3-8 current happy hours, restaurant deals, or cheap/free local events in Charlotte \
for this week. For each pick, include the venue, neighborhood (if known), a short \
description, the timing in plain language (e.g. "Tuesdays 5-7pm"), the deal type, and \
the source URL where you found it."""


class _DealsResponse(BaseModel):
    deals: list[DealPick] = Field(default_factory=list, max_length=8)


def fetch_deals(
    settings: Settings,
    *,
    week_start: date,
    week_end: date,
    client: Anthropic | None = None,
) -> list[DealPick]:
    """Ask Claude (with web_search) for current Charlotte happy hours and deals."""
    client = client or Anthropic(api_key=settings.anthropic_api_key.get_secret_value())

    log.info(
        "deals.fetch_start",
        model=settings.claude_deals_model,
        week_start=str(week_start),
        week_end=str(week_end),
    )

    user_content = _DEALS_USER_TEMPLATE.format(week_start=week_start, week_end=week_end)
    messages: list[MessageParam] = [{"role": "user", "content": user_content}]

    # Server-side web_search runs up to 10 iterations before returning `pause_turn`.
    # For find-3-8-deals work, one round trip is the norm. Allow a single continuation
    # so the agent can finish if it happens to hit the cap.
    # Sonnet 4.6 defaults to effort: "high" + adaptive thinking. Combined with web_search's
    # server-side agentic loop (up to 10 iterations), default config can cost $2+/call —
    # thinking fires *between every search iteration* and tokens compound. Explicit low
    # effort + disabled thinking keeps the model focused on tool calls, not reasoning,
    # which is what we want here: search, evaluate freshness, return structured output.
    response = None
    for attempt in range(2):
        response = client.messages.parse(
            model=settings.claude_deals_model,
            max_tokens=4096,
            thinking={"type": "disabled"},
            output_config={"effort": "low"},
            tools=[_WEB_SEARCH_TOOL],
            system=_DEALS_SYSTEM,
            messages=messages,
            output_format=_DealsResponse,
        )
        if response.stop_reason != "pause_turn":
            break
        log.info("deals.pause_turn_resume", attempt=attempt + 1)
        messages = [
            {"role": "user", "content": user_content},
            {"role": "assistant", "content": response.content},
        ]
    assert response is not None

    parsed = response.parsed_output
    if parsed is None:
        log.warning("deals.no_parsed_output", stop_reason=response.stop_reason)
        return []

    usage = response.usage
    log.info(
        "deals.fetch_done",
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        picks=len(parsed.deals),
    )
    return parsed.deals
