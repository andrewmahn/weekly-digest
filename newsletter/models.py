from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, HttpUrl


class EventSource(StrEnum):
    TICKETMASTER = "ticketmaster"
    SONGKICK = "songkick"


class DealType(StrEnum):
    HAPPY_HOUR = "happy_hour"
    RESTAURANT_SPECIAL = "restaurant_special"
    FREE_EVENT = "free_event"
    DISCOUNTED_EVENT = "discounted_event"


class CalendarEvent(BaseModel):
    """A single event read from Google Calendar."""

    id: str
    calendar_id: str
    title: str
    start: datetime
    end: datetime
    location: str | None = None
    description: str | None = None
    all_day: bool = False

    @property
    def day_of_week(self) -> str:
        return self.start.strftime("%A")

    @property
    def time_range(self) -> str:
        if self.all_day:
            return "all day"
        return f"{_fmt_time(self.start)}–{_fmt_time(self.end)}"  # noqa: RUF001 — intentional en-dash for display


def _fmt_time(dt: datetime) -> str:
    return dt.strftime("%I:%M %p").lstrip("0")


def _fmt_short_when(dt: datetime) -> str:
    return dt.strftime("%a %b %d, %I:%M %p").replace(" 0", " ").lstrip("0")


class DayForecast(BaseModel):
    date: date
    high_f: float
    low_f: float
    precipitation_chance: float = Field(ge=0, le=100)
    condition: str
    sunrise: datetime | None = None
    sunset: datetime | None = None

    @property
    def day_of_week(self) -> str:
        return self.date.strftime("%A")


class WeatherForecast(BaseModel):
    location: str
    days: list[DayForecast]


class CandidateEvent(BaseModel):
    """An event pulled from Ticketmaster / Songkick — to be ranked."""

    id: str
    source: EventSource
    title: str
    start: datetime
    venue: str | None = None
    venue_neighborhood: str | None = None
    url: HttpUrl
    image_url: HttpUrl | None = None
    category: str | None = None
    subcategory: str | None = None
    price_range: str | None = None
    # Numeric floor extracted from the source (Ticketmaster's priceRanges[0].min).
    # Used to gate mainstream/sell-out-risk shows behind a longer lead time.
    min_price: float | None = None
    description: str | None = None

    @property
    def short_when(self) -> str:
        return _fmt_short_when(self.start)


class RankedEvent(BaseModel):
    """A CandidateEvent enriched by Claude with a personalized reason."""

    event: CandidateEvent
    reason: str
    rank: int


class DealPick(BaseModel):
    """A happy hour, restaurant deal, or free/cheap local event surfaced by Claude web search."""

    title: str = Field(min_length=3, max_length=120)
    description: str = Field(min_length=10, max_length=400)
    venue: str | None = Field(default=None, max_length=120)
    neighborhood: str | None = Field(default=None, max_length=80)
    deal_type: DealType
    when: str | None = Field(
        default=None,
        max_length=120,
        description="Human-readable timing, e.g. 'Tuesdays 5-7pm' or 'Sunday, May 18'.",
    )
    source_url: HttpUrl


class Preferences(BaseModel):
    """Structured preference profile built monthly by Claude Haiku."""

    music_genres: list[str] = Field(default_factory=list)
    cuisine_likes: list[str] = Field(default_factory=list)
    cuisine_avoids: list[str] = Field(default_factory=list)
    venue_types: list[str] = Field(default_factory=list)
    activity_patterns: list[str] = Field(default_factory=list)
    avoids: list[str] = Field(default_factory=list)
    recent_event_titles: list[str] = Field(default_factory=list)
    notes: str | None = None
    built_at: datetime
    source_event_count: int


class NewsletterCommentary(BaseModel):
    """Short editorial blurbs written by Claude during the weekly personalization call."""

    editor_note: str = ""
    picks_intro: str = ""
    deals_intro: str = ""


class PersonalizationResult(BaseModel):
    """Everything the unified personalization call returns."""

    ranked_events: list[RankedEvent] = Field(default_factory=list)
    kept_deals: list[DealPick] = Field(default_factory=list)
    commentary: NewsletterCommentary = Field(default_factory=NewsletterCommentary)


class NewsletterContext(BaseModel):
    """Everything passed to the Jinja2 template."""

    generated_at: datetime
    week_start: date
    week_end: date
    city_name: str
    calendar_events: list[CalendarEvent]
    weather: WeatherForecast | None
    ranked_events: list[RankedEvent]
    deals: list[DealPick] = Field(default_factory=list)
    commentary: NewsletterCommentary = Field(default_factory=NewsletterCommentary)
    section_errors: dict[str, str] = Field(default_factory=dict)

    def model_dump_for_template(self) -> dict[str, Any]:
        return self.model_dump(mode="json")
