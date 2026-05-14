"""Deals source — scrape Charlotte On The Cheap's RSS feed.

charlotteonthecheap.com curates Charlotte-area free events, restaurant deals, and
happy hours and exposes its full posting stream as a WordPress RSS feed at /feed/.
Each item carries title, link, pubDate, categories, and an HTML description — enough
to surface as a DealPick without any LLM call. Saves the per-run Sonnet + web_search
spend (~$0.15-0.35/run, the dominant Anthropic line item).

The feed returns the 100 most-recent posts. We filter to items published within the
two-week window leading up to week_start (older posts overwhelmingly cover past events),
drop aggregator round-ups, strip WordPress boilerplate from the description, and cap
the list at 8 picks to mirror the prior prompt's quality-over-quantity intent.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, timedelta
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from xml.etree import ElementTree as ET

import httpx
from pydantic import HttpUrl, ValidationError

from newsletter.config import Settings
from newsletter.logging_config import get_logger
from newsletter.models import DealPick, DealType

log = get_logger(__name__)

FEED_URL = "https://charlotteonthecheap.com/feed/"
_USER_AGENT = "weekly-digest/0.1 (+https://github.com/andrewmahn/weekly-digest)"

# Aggregator/round-up posts ("Free and cheap things to do in Charlotte this week",
# "Best of summer") are summaries that link to the same items we'll pull individually —
# skip them so the deals section doesn't double-count.
_AGGREGATOR_PATTERNS = (
    re.compile(r"free and cheap things to do", re.I),
    re.compile(r"\bbest of\b", re.I),
)

_HAPPY_HOUR_RE = re.compile(r"happy hour|half[- ]?price|prix fixe|\$\d+\s*off", re.I)
_FREE_RE = re.compile(r"\bfree\b", re.I)

_WP_FOOTER_RE = re.compile(r"\s*The post .+? appeared first on .+$", re.S)


class _TextExtractor(HTMLParser):
    """Collapse an HTML fragment to plain text without pulling in BeautifulSoup."""

    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self._parts.append(data)

    @property
    def text(self) -> str:
        return "".join(self._parts)


def _strip_html(html: str) -> str:
    parser = _TextExtractor()
    parser.feed(html)
    text = _WP_FOOTER_RE.sub("", parser.text)
    return re.sub(r"\s+", " ", text).strip()


def _classify(title: str, categories: list[str]) -> DealType:
    cat_set = {c.lower() for c in categories}
    if _HAPPY_HOUR_RE.search(title):
        return DealType.HAPPY_HOUR
    if "food and drink" in cat_set:
        return DealType.RESTAURANT_SPECIAL
    if _FREE_RE.search(title):
        return DealType.FREE_EVENT
    return DealType.DISCOUNTED_EVENT


def _is_aggregator(title: str) -> bool:
    return any(p.search(title) for p in _AGGREGATOR_PATTERNS)


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def fetch_deals(
    settings: Settings,
    *,
    week_start: date,
    week_end: date,
    feed_url: str = FEED_URL,
    max_picks: int = 8,
) -> list[DealPick]:
    """Pull current happy hours, restaurant specials, and free events from the COTC feed."""
    log.info(
        "deals.fetch_start",
        feed=feed_url,
        week_start=str(week_start),
        week_end=str(week_end),
    )

    headers = {
        "User-Agent": _USER_AGENT,
        "Accept": "application/rss+xml, application/xml;q=0.9, */*;q=0.5",
    }
    response = httpx.get(feed_url, headers=headers, timeout=30.0, follow_redirects=True)
    response.raise_for_status()

    root = ET.fromstring(response.content)
    channel = root.find("channel")
    if channel is None:
        log.warning("deals.no_channel")
        return []

    cutoff = datetime.combine(week_start, datetime.min.time(), UTC) - timedelta(days=14)

    picks: list[DealPick] = []
    skipped = 0
    for item in channel.iterfind("item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        if not title or not link or _is_aggregator(title):
            continue

        pub_raw = (item.findtext("pubDate") or "").strip()
        try:
            published = parsedate_to_datetime(pub_raw)
        except (TypeError, ValueError):
            continue
        if published < cutoff:
            continue

        description = _strip_html(item.findtext("description") or "")
        if len(description) < 10:
            continue

        categories = [c.text.strip() for c in item.findall("category") if c.text]

        try:
            picks.append(
                DealPick(
                    title=_truncate(title, 120),
                    description=_truncate(description, 400),
                    deal_type=_classify(title, categories),
                    source_url=HttpUrl(link),
                )
            )
        except ValidationError as exc:
            skipped += 1
            log.debug("deals.skip_invalid", title=title, error=str(exc))
            continue

        if len(picks) >= max_picks:
            break

    log.info("deals.fetch_done", picks=len(picks), skipped=skipped)
    return picks
