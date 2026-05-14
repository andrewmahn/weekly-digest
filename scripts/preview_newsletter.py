"""Render the newsletter template against a realistic synthetic context.

Lets us iterate on newsletter/templates/newsletter.html.j2 without burning
Anthropic spend or hitting Calendar/Ticketmaster. Run:

    uv run python scripts/preview_newsletter.py

Writes out/preview.html. Open in a browser to inspect.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

from newsletter.models import (
    CalendarEvent,
    CandidateEvent,
    DayForecast,
    DealPick,
    DealType,
    EventSource,
    NewsletterCommentary,
    NewsletterContext,
    RankedEvent,
    WeatherForecast,
)
from newsletter.render import render_newsletter, write_to_disk


def build_context() -> NewsletterContext:
    week_start = date(2026, 5, 17)

    calendar_events = [
        CalendarEvent(
            id="c1",
            calendar_id="primary",
            title="Brunch with Sarah & Tom",
            start=datetime(2026, 5, 17, 11, 0, tzinfo=UTC),
            end=datetime(2026, 5, 17, 13, 0, tzinfo=UTC),
            location="Optimist Hall, Charlotte",
        ),
        CalendarEvent(
            id="c2",
            calendar_id="primary",
            title="Yoga at Y2",
            start=datetime(2026, 5, 19, 18, 0, tzinfo=UTC),
            end=datetime(2026, 5, 19, 19, 15, tzinfo=UTC),
        ),
        CalendarEvent(
            id="c3",
            calendar_id="primary",
            title="Dinner — anniversary",
            start=datetime(2026, 5, 22, 19, 30, tzinfo=UTC),
            end=datetime(2026, 5, 22, 21, 30, tzinfo=UTC),
            location="Kindred, Davidson",
        ),
    ]

    weather = WeatherForecast(
        location="Charlotte, NC",
        days=[
            DayForecast(date=date(2026, 5, 17), high_f=78, low_f=62, precipitation_chance=10, condition="Mostly clear"),
            DayForecast(date=date(2026, 5, 18), high_f=82, low_f=65, precipitation_chance=45, condition="Showers"),
            DayForecast(date=date(2026, 5, 19), high_f=80, low_f=64, precipitation_chance=20, condition="Partly cloudy"),
            DayForecast(date=date(2026, 5, 20), high_f=83, low_f=66, precipitation_chance=10, condition="Sunny"),
            DayForecast(date=date(2026, 5, 21), high_f=85, low_f=68, precipitation_chance=5, condition="Sunny"),
            DayForecast(date=date(2026, 5, 22), high_f=86, low_f=70, precipitation_chance=15, condition="Mostly sunny"),
            DayForecast(date=date(2026, 5, 23), high_f=84, low_f=68, precipitation_chance=30, condition="Scattered storms"),
        ],
    )

    ranked = [
        RankedEvent(
            rank=1,
            reason=(
                "Big Thief at The Fillmore — same indie folk lineage as the Vampire Weekend "
                "show you went to last month, and Friday's clear and 83°."
            ),
            event=CandidateEvent(
                id="tm1",
                source=EventSource.TICKETMASTER,
                title="Big Thief",
                start=datetime(2026, 5, 22, 20, 0),
                venue="The Fillmore Charlotte",
                venue_neighborhood="NoDa",
                url="https://www.ticketmaster.com/event/tm1",
                image_url="https://s1.ticketm.net/dam/a/8b6/6c8caefd-8d5b-4f6e-9b8b-6f1a5d9b88b6_RETINA_PORTRAIT_16_9.jpg",
                category="Music",
                subcategory="Indie Folk",
                price_range="$45–$85",
                min_price=45.0,
            ),
        ),
        RankedEvent(
            rank=2,
            reason=(
                "Khruangbin headlines a Saturday outdoor show — fits your bar-hopping-then-show "
                "Saturday pattern and matches the funk/psych-rock you've been catching."
            ),
            event=CandidateEvent(
                id="tm2",
                source=EventSource.TICKETMASTER,
                title="Khruangbin with Men I Trust",
                start=datetime(2026, 6, 6, 19, 30),
                venue="Skyla Credit Union Amphitheatre",
                url="https://www.ticketmaster.com/event/tm2",
                image_url="https://s1.ticketm.net/dam/a/d0e/76e7c8b4-9b8c-4e8b-9f2e-3d4c8b1c0d0e_RETINA_PORTRAIT_16_9.jpg",
                category="Music",
                subcategory="Psych Rock",
                price_range="$55–$120",
                min_price=55.0,
            ),
        ),
        RankedEvent(
            rank=3,
            reason=(
                "Charlotte Symphony's all-Rachmaninoff night at Knight Theater — same intimate-venue "
                "type as the Booth Playhouse evenings on your calendar."
            ),
            event=CandidateEvent(
                id="tm3",
                source=EventSource.TICKETMASTER,
                title="Charlotte Symphony: Rachmaninoff & Ravel",
                start=datetime(2026, 5, 30, 19, 30),
                venue="Knight Theater",
                venue_neighborhood="Uptown",
                url="https://www.ticketmaster.com/event/tm3",
                image_url="https://s1.ticketm.net/dam/a/4f1/a8b3c2d1-0e9f-4a8b-b3c2-d10e9f4a8bc1_RETINA_PORTRAIT_16_9.jpg",
                category="Music",
                subcategory="Classical",
                price_range="$32–$90",
                min_price=32.0,
            ),
        ),
        RankedEvent(
            rank=4,
            reason=(
                "Comedy at The Comedy Zone — Sam Morril is the kind of dry, narrative stand-up "
                "you've gravitated toward (saw him on Netflix in your watch history)."
            ),
            event=CandidateEvent(
                id="tm4",
                source=EventSource.TICKETMASTER,
                title="Sam Morril: Class Act Tour",
                start=datetime(2026, 6, 13, 20, 0),
                venue="The Comedy Zone Charlotte",
                url="https://www.ticketmaster.com/event/tm4",
                image_url="https://s1.ticketm.net/dam/a/2f8/c7b3d8a1-2f8e-4c7b-3d8a-12f8e4c7b3d8_RETINA_PORTRAIT_16_9.jpg",
                category="Comedy",
                price_range="$35–$60",
                min_price=35.0,
            ),
        ),
    ]

    deals = [
        DealPick(
            title="Pineville WorldFest May 30",
            description=(
                "Free multicultural festival at Pineville Lake Park, May 30 from noon to 8pm — "
                "food, music from a dozen cultural groups, kids' crafts, and a global market."
            ),
            deal_type=DealType.FREE_EVENT,
            when="Saturday, May 30",
            venue="Pineville Lake Park",
            neighborhood="Pineville",
            source_url="https://www.charlotteonthecheap.com/pineville-world-fest/",
            image_url="https://www.charlotteonthecheap.com/lotc-cms/wp-content/uploads/2026/05/pineville-world-fest.jpg",
        ),
        DealPick(
            title="Night Market at Pascuales' Farm",
            description=(
                "Pascuales' Farm hosts a Thursday-night market through June 25, 5–8pm. "
                "Local vendors, a Latin dance class, food trucks. Free to attend."
            ),
            deal_type=DealType.RESTAURANT_SPECIAL,
            when="Thursdays through June 25",
            venue="Pascuales' Farm",
            neighborhood="East Charlotte",
            source_url="https://www.charlotteonthecheap.com/pascuales-farm-market/",
            image_url="https://www.charlotteonthecheap.com/lotc-cms/wp-content/uploads/2026/04/pascuales-farm-night-market-1-1024x536.jpg",
        ),
        DealPick(
            title="Half-price oysters at The Stanley",
            description=(
                "The Stanley in Elizabeth runs half-price oysters every Tuesday from 5 to 7pm "
                "— the chef's pick rotates weekly."
            ),
            deal_type=DealType.HAPPY_HOUR,
            when="Tuesdays 5–7pm",
            venue="The Stanley",
            neighborhood="Elizabeth",
            source_url="https://www.charlotteonthecheap.com/stanley-oysters/",
            image_url="https://www.charlotteonthecheap.com/lotc-cms/wp-content/uploads/2026/01/franks-beer-shop-819x1024.jpeg",
        ),
        DealPick(
            title="Live music at Frank's Beer Shop",
            description=(
                "Neighborhood bar and bottle shop in Plaza Midwood, dogs welcome. "
                "Free live music most weekends — check their Facebook for the lineup."
            ),
            deal_type=DealType.RESTAURANT_SPECIAL,
            when="Weekends, free",
            venue="Frank's Beer Shop",
            neighborhood="Plaza Midwood",
            source_url="https://www.charlotteonthecheap.com/franks-beer-shop/",
            image_url="https://www.charlotteonthecheap.com/lotc-cms/wp-content/uploads/2026/01/franks-beer-shop-819x1024.jpeg",
        ),
        DealPick(
            title="Game Night at Confluence in Cramerton",
            description=(
                "Confluence is a riverside arts center on the South Fork — bar, gallery, "
                "venue. Free Saturday game nights with rotating board-game library."
            ),
            deal_type=DealType.FREE_EVENT,
            when="Saturdays",
            venue="Confluence",
            neighborhood="Cramerton",
            source_url="https://www.charlotteonthecheap.com/confluence-south-fork/",
            # No image — exercise the missing-image fallback path.
            image_url=None,
        ),
    ]

    commentary = NewsletterCommentary(
        editor_note=(
            "Big Thief at The Fillmore on Friday is the standout — clear weather, your kind "
            "of indie folk, and you have the night open. The Pineville WorldFest two weeks "
            "out is worth blocking off too."
        ),
        picks_intro=(
            "Indie folk has the strongest run this week — Big Thief and Khruangbin both "
            "land in your wheelhouse, and the Symphony's Rachmaninoff night is a quieter "
            "alternative for the following weekend."
        ),
        deals_intro=(
            "A free multicultural festival, a Thursday-night farm market, and a half-price "
            "oyster night — three quiet wins that don't need a reservation weeks out."
        ),
    )

    return NewsletterContext(
        generated_at=datetime.now(UTC),
        week_start=week_start,
        week_end=date(2026, 5, 23),
        city_name="Charlotte, NC",
        calendar_events=calendar_events,
        weather=weather,
        ranked_events=ranked,
        deals=deals,
        commentary=commentary,
    )


def main() -> None:
    context = build_context()
    html = render_newsletter(context)
    out_path = Path(__file__).parent.parent / "out" / "preview.html"
    write_to_disk(html, out_path)
    print(f"Wrote {out_path} ({len(html):,} bytes)")


if __name__ == "__main__":
    main()
