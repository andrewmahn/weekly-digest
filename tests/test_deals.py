"""Test the deals source against a mocked Charlotte On The Cheap RSS feed.

We exercise the parse path: given a realistic feed payload, do we produce the right
DealPick list? Network is mocked with respx — no real HTTP.
"""

from __future__ import annotations

from datetime import date

import httpx
import respx

from newsletter.config import Settings
from newsletter.models import DealType
from newsletter.sources.deals import FEED_URL, fetch_deals


def _item(
    *,
    title: str,
    link: str,
    pub_date: str = "Wed, 13 May 2026 20:00:00 +0000",
    description: str = "<p>Details about the event with venue address and timing.</p>",
    categories: tuple[str, ...] = (),
    content_encoded: str | None = None,
) -> str:
    cats = "".join(f"<category><![CDATA[{c}]]></category>" for c in categories)
    encoded = (
        f"<content:encoded><![CDATA[{content_encoded}]]></content:encoded>"
        if content_encoded is not None
        else ""
    )
    return (
        "<item>"
        f"<title>{title}</title>"
        f"<link>{link}</link>"
        f"<pubDate>{pub_date}</pubDate>"
        f"{cats}"
        f"<description><![CDATA[{description}]]></description>"
        f"{encoded}"
        "</item>"
    )


def _feed(items: list[str]) -> str:
    body = "".join(items)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/"><channel>'
        "<title>Charlotte On The Cheap</title>"
        f"{body}"
        "</channel></rss>"
    )


@respx.mock
def test_fetch_deals_parses_feed(settings: Settings) -> None:
    feed = _feed(
        [
            _item(
                title="Half-price oyster happy hour at The Stanley",
                link="https://charlotteonthecheap.com/stanley-oysters/",
                categories=("Food and Drink",),
                description=(
                    "<p>The Stanley in Elizabeth runs half-price oysters every Tuesday "
                    "from 5 to 7pm.</p>"
                    '<p>The post <a href="https://charlotteonthecheap.com/stanley-oysters/">'
                    "Half-price oysters</a> appeared first on "
                    '<a href="https://charlotteonthecheap.com">Charlotte On The Cheap</a>.</p>'
                ),
            ),
            _item(
                title="Free outdoor movie at Romare Bearden Park",
                link="https://charlotteonthecheap.com/movie-park/",
                categories=("Free Events", "Kids"),
                description="<p>Bring a blanket Friday at 8pm for The Princess Bride.</p>",
            ),
        ]
    )
    respx.get(FEED_URL).mock(return_value=httpx.Response(200, content=feed))

    picks = fetch_deals(settings, week_start=date(2026, 5, 17), week_end=date(2026, 5, 23))

    assert len(picks) == 2
    happy = picks[0]
    assert happy.title.startswith("Half-price oyster")
    assert happy.deal_type == DealType.HAPPY_HOUR
    assert "appeared first on" not in happy.description
    assert "half-price oysters" in happy.description.lower()

    free = picks[1]
    assert free.deal_type == DealType.FREE_EVENT


@respx.mock
def test_fetch_deals_skips_aggregator_roundups(settings: Settings) -> None:
    feed = _feed(
        [
            _item(
                title="Free and cheap things to do in Charlotte this week",
                link="https://charlotteonthecheap.com/freethingstodo/",
            ),
            _item(
                title="Game Night every Saturday at Confluence",
                link="https://charlotteonthecheap.com/confluence-game-night/",
            ),
        ]
    )
    respx.get(FEED_URL).mock(return_value=httpx.Response(200, content=feed))

    picks = fetch_deals(settings, week_start=date(2026, 5, 17), week_end=date(2026, 5, 23))

    assert len(picks) == 1
    assert "Confluence" in picks[0].title


@respx.mock
def test_fetch_deals_drops_items_older_than_cutoff(settings: Settings) -> None:
    feed = _feed(
        [
            _item(
                title="Fresh post — Live music at Frank's Beer Shop",
                link="https://charlotteonthecheap.com/franks/",
                pub_date="Mon, 11 May 2026 12:00:00 +0000",
            ),
            _item(
                title="Stale post from last year",
                link="https://charlotteonthecheap.com/stale/",
                pub_date="Fri, 01 Mar 2025 12:00:00 +0000",
            ),
        ]
    )
    respx.get(FEED_URL).mock(return_value=httpx.Response(200, content=feed))

    picks = fetch_deals(settings, week_start=date(2026, 5, 17), week_end=date(2026, 5, 23))

    assert len(picks) == 1
    assert "Frank" in picks[0].title


@respx.mock
def test_fetch_deals_respects_max_picks(settings: Settings) -> None:
    items = [
        _item(
            title=f"Pick number {i}",
            link=f"https://charlotteonthecheap.com/pick-{i}/",
        )
        for i in range(15)
    ]
    respx.get(FEED_URL).mock(return_value=httpx.Response(200, content=_feed(items)))

    picks = fetch_deals(
        settings,
        week_start=date(2026, 5, 17),
        week_end=date(2026, 5, 23),
        max_picks=5,
    )

    assert len(picks) == 5


@respx.mock
def test_fetch_deals_extracts_image_from_content_encoded(settings: Settings) -> None:
    feed = _feed(
        [
            _item(
                title="Pineville WorldFest May 30",
                link="https://charlotteonthecheap.com/pineville-world-fest/",
                content_encoded=(
                    '<figure class="wp-block-image"><img fetchpriority="high" '
                    'width="616" height="514" '
                    'src="https://www.charlotteonthecheap.com/uploads/pineville.jpg" '
                    'alt=""/></figure>'
                    "<p>Free multicultural festival May 30 at Pineville Lake Park.</p>"
                ),
            ),
            _item(
                title="No-image deal post",
                link="https://charlotteonthecheap.com/no-image/",
                content_encoded="<p>Plain post body with no embedded image.</p>",
            ),
        ]
    )
    respx.get(FEED_URL).mock(return_value=httpx.Response(200, content=feed))

    picks = fetch_deals(settings, week_start=date(2026, 5, 17), week_end=date(2026, 5, 23))

    assert len(picks) == 2
    assert (
        str(picks[0].image_url)
        == "https://www.charlotteonthecheap.com/uploads/pineville.jpg"
    )
    assert picks[1].image_url is None


@respx.mock
def test_fetch_deals_returns_empty_when_channel_missing(settings: Settings) -> None:
    respx.get(FEED_URL).mock(
        return_value=httpx.Response(200, content='<?xml version="1.0"?><rss></rss>')
    )

    picks = fetch_deals(settings, week_start=date(2026, 5, 17), week_end=date(2026, 5, 23))

    assert picks == []
