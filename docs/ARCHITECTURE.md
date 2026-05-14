# Architecture

## System diagram

```
┌────────────────────────────────────────────────────────────────────────┐
│  GitHub Actions (cron, UTC)                                            │
│                                                                        │
│   weekly-newsletter.yml   ─ Sun 11:07 UTC ─→ python -m newsletter.main │
│       │                                       --weekly                 │
│   monthly-profile.yml     ─ 1st 11:07 UTC ─→ python -m newsletter.main │
│       │                                       --profile                │
│   ci.yml                  ─ PR push ──→ ruff + mypy + pytest           │
└────────────────────────────────────────────────────────────────────────┘
            │
            ▼
┌────────────────────────────────────────────────────────────────────────┐
│  newsletter package                                                    │
│                                                                        │
│   main.py ─┬─ sources/calendar.py     ─→  Google Calendar API         │
│            ├─ sources/weather.py      ─→  Open-Meteo (keyless)        │
│            ├─ sources/ticketmaster.py ─→  Ticketmaster Discovery API  │
│            ├─ sources/songkick.py     ─→  Songkick (optional)         │
│            ├─ sources/deals.py        ─→  Anthropic API (web_search)  │
│            │                                                          │
│            ├─ personalize.py          ─→  Anthropic API                │
│            │   • build_profile (Haiku 4.5, monthly)                   │
│            │   • rank_events   (Sonnet 4.6, weekly)                   │
│            │                                                          │
│            ├─ render.py               ─→  Jinja2 → HTML → premailer   │
│            │                                                          │
│            └─ send.py                 ─→  Resend API                  │
└────────────────────────────────────────────────────────────────────────┘
            │
            ▼
   Two inboxes — Sunday 7:07 ET
```

## Design decisions

### Personalization pipeline

**Tiered model selection.** Haiku 4.5 for the monthly summarization (cheap, large input). Sonnet 4.6 for the weekly ranking (judgment, smaller input). Total cost is < $5/year.

**Hybrid context.** A pure JSON preference profile is too lossy for ranking — it loses signal that "I went to three jazz shows last month" carries. The profile build also extracts the **last ~15 attended event titles verbatim** (sanitized) and feeds both to the ranking call. The JSON gives Claude top-level steering; the recent titles give it concrete grounding to compare against.

**Structured outputs everywhere.** Both Claude calls use `client.messages.parse()` with Pydantic schemas. No JSON-in-text parsing.

**No prompt caching.** The 5-minute / 1-hour cache TTL doesn't survive the 7-day gap between weekly runs. Reads would always miss; writes would just add the cache-creation premium with no payoff.

**Explicit `effort: "low"` + `thinking: {"type": "disabled"}` on both Sonnet 4.6 calls.** Sonnet 4.6 defaults to `effort: "high"` with adaptive thinking enabled, which is the right default for hard agentic work but burns thousands of thinking tokens on simpler structured-output tasks like ranking and tool-driven search. Verified empirically: the first dry-run with default settings cost $3.24 in Sonnet tokens for a single weekly newsletter. Explicit low effort + no thinking brings the same calls down to ~$0.30–0.50 with no measurable quality loss on either task.

### Cost breakdown (weekly run, with controls)

| Call | Model | Approx cost |
|---|---|---|
| Profile build (monthly only) | Haiku 4.5 | ~$0.01 |
| Weekly ranking | Sonnet 4.6 (effort low, thinking off) | ~$0.05–0.15 |
| Weekly deals (web_search) | Sonnet 4.6 (effort low, thinking off) | ~$0.15–0.35 (incl. web_search fees) |
| **Annual total** | | **~$15–25** |

### Deals via Claude web_search

The "happy hours & deals" section delegates discovery to Claude with Anthropic's server-side `web_search` tool (`web_search_20260209`, the version with dynamic filtering). Once a week the call hits the open web for current Charlotte happy hours, restaurant specials, and free/cheap events, and returns a typed `list[DealPick]` via `messages.parse()` — the same structured-output pattern as the ranking step.

**Why this instead of an aggregator API?** There's no clean public API for "current Charlotte happy hours." Yelp Fusion has restaurant listings but rarely populates `special_hours`; Eventbrite's public search endpoint was deprecated in 2020; Groupon is partner-only. The realistic alternatives are scraping local-news RSS or a curated YAML list — both have maintenance debt and no portfolio value. Letting Claude search and curate is roughly the price of `$0.04/month` and produces fresher results than any static list.

**Failure mode.** A non-empty result is not guaranteed — Charlotte may have a quiet week, or Claude may decide nothing on the web is current enough. The newsletter renders an empty deals section gracefully. The call is wrapped in `_safe()` in `main.py` so an Anthropic outage doesn't kill the whole run.

### Privacy

**`preferences.json` is never committed to the public repo.** Even after the LLM rewrite, calendar event titles can carry residue — therapists, kids' names, friends' birthdays. The file lives in the GitHub Actions cache (key: `preferences-v1-<YYYY-MM>`) and is excluded from git via `.gitignore`.

`GOOGLE_CALENDAR_IDS` is a secret because calendar IDs often embed the account owner's email.

### Resilience

**Per-source try/except** in `main.py::run_weekly`. A failing source renders as "data unavailable" in the relevant section; the newsletter still ships. This matters more than it sounds — APIs go down, keys get rotated, free-tier quotas hit limits. A weekly automation that drops the whole email because one provider is having a bad day is not worth running.

**Failure notification.** If the GitHub Actions run itself fails (auth error, bad code), a separate workflow step sends a notification via Resend. Silent failures are worse than loud ones.

**Cold-start fallback.** If the weekly run hits a cache miss on `preferences.json` (first run ever, or cache evicted), `main.py` builds the profile inline rather than failing. The weekly run takes slightly longer but still ships.

### Scheduling

GitHub Actions cron is UTC-only. `7 11 * * 0` lands at 7:07am EDT or 6:07am EST depending on the season. Documented and intentional — short-circuiting in Python adds complexity for cosmetic precision, given that GitHub Actions cron drifts 5–15 minutes under load anyway.

Off-minute (`:07`) avoids the top-of-hour scheduler stampede where every cron job in the world fires simultaneously.

### Email rendering

**Jinja2 + premailer.** Premailer inlines CSS onto each element. Gmail strips most `<style>` blocks in many contexts; inline styles are the only reliable path.

`@media` queries (mobile responsive, dark mode) stay in `<style>` blocks (premailer's `keep_style_tags=True`) — Gmail supports them in `<style>` even when stripping other rules.

### Stack choices and rejected alternatives

| Component | Choice | Rejected |
|---|---|---|
| Email delivery | Resend | Gmail SMTP (requires app passwords; less professional) |
| Event source | Ticketmaster + Songkick | Eventbrite (public search API deprecated 2024), PredictHQ (paid) |
| Deals & happy hours | Claude `web_search` once a week | Yelp Fusion (`special_hours` rarely populated, API gated), Reddit r/Charlotte (low signal — empirically tested), Groupon (deprecated for new apps), curated YAML list (maintenance burden, no freshness) |
| Dependency manager | `uv` | Poetry (slower), pip-tools (more manual) |
| Test mocking | `respx` for HTTP | `vcrpy` cassettes (planned for v1.1) |

### Project layout rationale

```
newsletter/
  sources/      ← one file per external API; thin parsing logic
  personalize.py ← all Claude calls in one place
  render.py     ← template + inlining
  send.py       ← Resend client
  main.py       ← orchestration; the only file that knows about all of the above
```

Sources don't know about each other. Personalization doesn't know about render. Render doesn't know about send. `main.py` is the only file that orchestrates — everything else is independently testable.
