from datetime import UTC, date, datetime

from newsletter.models import NewsletterContext
from newsletter.render import render_newsletter


def test_render_full_newsletter(sample_context: NewsletterContext) -> None:
    html = render_newsletter(sample_context)

    assert "<html" in html.lower()
    assert "Weekly Digest" in html
    assert "Charlotte, NC" in html
    assert "Big Thief at The Fillmore" in html
    # Deals section
    assert "The Stanley" in html
    assert "Half-price oysters" in html
    assert "Mostly clear" in html
    # Personalized reason should be visible
    assert "Vampire Weekend" in html
    # premailer should have inlined styles — look for inline `style=` attributes
    assert 'style="' in html


def test_render_empty_calendar() -> None:
    context = NewsletterContext(
        generated_at=datetime(2026, 5, 17, tzinfo=UTC),
        week_start=date(2026, 5, 17),
        week_end=date(2026, 5, 23),
        city_name="Charlotte, NC",
        calendar_events=[],
        weather=None,
        ranked_events=[],
        deals=[],
        section_errors={"calendar": "AuthError"},
    )
    html = render_newsletter(context)
    assert "Couldn&#39;t pull calendar" in html or "Couldn't pull calendar" in html


def test_render_section_errors_surface(sample_context: NewsletterContext) -> None:
    sample_context.weather = None
    sample_context.section_errors = {"weather": "HTTPError"}
    html = render_newsletter(sample_context)
    assert "Weather data unavailable" in html
