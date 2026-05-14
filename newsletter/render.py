from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from premailer import transform

from newsletter.logging_config import get_logger
from newsletter.models import NewsletterContext

log = get_logger(__name__)

_TEMPLATE_DIR = Path(__file__).parent / "templates"


def _build_env() -> Environment:
    return Environment(
        loader=FileSystemLoader(_TEMPLATE_DIR),
        autoescape=select_autoescape(["html", "xml"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )


def render_newsletter(context: NewsletterContext) -> str:
    """Render the newsletter to HTML with CSS inlined for Gmail compatibility.

    Returns a self-contained HTML string ready to send.
    """
    env = _build_env()
    template = env.get_template("newsletter.html.j2")
    # Pass the model objects directly (not model_dump'd) so Jinja2 can access
    # computed properties like `day_of_week` and `short_when`.
    raw_html = template.render(
        generated_at=context.generated_at,
        week_start=context.week_start,
        week_end=context.week_end,
        city_name=context.city_name,
        calendar_events=context.calendar_events,
        weather=context.weather,
        ranked_events=context.ranked_events,
        deals=context.deals,
        section_errors=context.section_errors,
    )

    log.info("render.template_rendered", raw_size=len(raw_html))

    # premailer inlines the <style> rules onto each element. Gmail strips <style>
    # blocks in many contexts, so inline styles are the only reliable path.
    inlined = transform(
        raw_html,
        keep_style_tags=True,  # keep @media queries (mobile + dark mode) in <style>
        cssutils_logging_level="CRITICAL",
        disable_validation=True,
    )
    log.info("render.css_inlined", final_size=len(inlined))
    return str(inlined)


def write_to_disk(html: str, path: Path) -> None:
    """Write rendered HTML to a file for local preview / dry-run inspection."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")
    log.info("render.written_to_disk", path=str(path))
