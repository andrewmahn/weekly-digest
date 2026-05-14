# weekly-digest

A personalized weekly newsletter for Charlotte, NC — delivered every Sunday at 7am ET to a couple's inboxes. Pulls the week ahead from Google Calendar, the 7-day forecast from Open-Meteo, upcoming concerts and events from Ticketmaster and Songkick, and current happy hours and restaurant deals via Claude's web_search tool — then uses Claude Sonnet to rank recommendations against a calendar-history-derived preference profile, with a short "why this for you" reason per pick.

![newsletter screenshot](docs/screenshots/newsletter.png)

> *Screenshot placeholder — see `docs/screenshots/newsletter.png` after first send.*

## Why this exists

A standing weekend-planning conversation, automated. Each Sunday morning before coffee, a clean HTML email lands in both inboxes with everything you'd otherwise spend Saturday afternoon pulling together from five different tabs.

The personalization layer is what makes it more than an RSS roll-up: a monthly background job scans the last six months of shared calendar events and writes a structured preference profile (music genres you actually attend, cuisines you actually eat, venues you actually go back to). The weekly job feeds that profile plus the next-week event candidates to Claude Sonnet, which ranks them and writes a single-sentence reason for each pick tied to a real signal from your history.

A second weekly Claude call uses the server-side `web_search` tool to find current Charlotte happy hours and restaurant specials — there's no clean API for that data, so we delegate discovery to the model and have it return a structured list with source URLs for attribution.

## Architecture

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the full system diagram and design notes.

```
GitHub Actions cron (Sun 11:07 UTC)
        │
        ▼
   newsletter.main ──► sources/* ──► personalize ──► render ──► send (Resend)
                       │              │
                       │              └─► Claude Sonnet 4.6 (weekly rank)
                       │
                       └─► Google Calendar, Open-Meteo, Ticketmaster, Songkick,
                           Claude web_search (happy hours & deals)

GitHub Actions cron (1st of month 11:07 UTC)
        │
        ▼
   newsletter.main --profile ──► Claude Haiku 4.5 ──► preferences.json
                                                       (GH Actions cache)
```

## Tech

- **Python 3.11+**, deps managed with [uv](https://github.com/astral-sh/uv)
- **Anthropic Claude** — Haiku 4.5 for profile-building (cheap summarization), Sonnet 4.6 for weekly ranking (judgment task), Sonnet 4.6 with the server-side `web_search` tool for current happy hours and deals (agentic tool use with structured outputs)
- **Jinja2 + premailer** — HTML templating with inlined CSS for Gmail compatibility
- **Resend** — transactional delivery
- **GitHub Actions** — cron scheduling, free for public repos
- **pytest + respx + vcrpy** — unit tests with recorded API fixtures
- **ruff + mypy --strict** — enforced in CI

## Quick start (local development)

```bash
# Install dependencies
uv sync

# Copy and fill in environment variables
cp .env.example .env
# ... edit .env with your keys ...

# One-time: generate a Google Calendar refresh token
uv run python scripts/generate_calendar_token.py

# Build a preference profile from your calendar history
uv run python -m newsletter.main --profile

# Render the newsletter to disk without sending (good for iterating on the template)
uv run python -m newsletter.main --weekly --dry-run

# Send the newsletter for real (to recipients in NEWSLETTER_TO_EMAILS)
uv run python -m newsletter.main --weekly
```

## Setup

Full setup instructions including Google OAuth consent-screen publishing, Resend domain verification, and the GitHub secrets checklist live in [docs/SETUP.md](docs/SETUP.md).

## Scheduling notes

The GitHub Actions cron runs in UTC. `7 11 * * 0` fires Sunday at 11:07 UTC, which lands at **7:07 am EDT** (March–November) or **6:07 am EST** (November–March). The DST drift is intentional and undocumented in `cron` — fighting it costs more complexity than it's worth at this cadence.

## Costs

- **Resend:** free (3000/mo cap; this project uses ~8/mo)
- **Open-Meteo, Ticketmaster, Songkick:** free
- **Anthropic API:** ~$15–25/year, dominated by the weekly `web_search` deals call. The Sonnet 4.6 calls use `effort: "low"` with adaptive thinking disabled — without those controls the same calls cost roughly 10× more (verified the hard way during the first dry-run). See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the breakdown.

## License

MIT — see [LICENSE](LICENSE).
