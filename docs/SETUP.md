# Setup

End-to-end first-run checklist. Plan for ~30 minutes the first time through.

## 1. Local development environment

```bash
git clone https://github.com/<your-username>/weekly-digest.git
cd weekly-digest

# Install uv if you don't have it
curl -LsSf https://astral.sh/uv/install.sh | sh   # macOS / Linux
# or: irm https://astral.sh/uv/install.ps1 | iex  (Windows PowerShell)

uv sync

cp .env.example .env
# ... fill in values as you obtain them in the steps below ...
```

## 2. Google Cloud Console — Calendar API

This is the most involved step. **Plan ~15 minutes.**

1. Go to https://console.cloud.google.com and create a new project (or pick an existing one).
2. **Enable the Google Calendar API:**
   - APIs & Services → Library → search "Google Calendar API" → Enable.
3. **Configure the OAuth consent screen:**
   - APIs & Services → OAuth consent screen.
   - User type: **External**.
   - App name: `weekly-digest` (or whatever you like — your future self will see this).
   - User support email: your email.
   - Developer contact: your email.
   - Scopes: add `.../auth/calendar.readonly`.
   - Test users: add your email AND your girlfriend's email (so both calendars are accessible).
   - **CRITICAL — publish the consent screen to Production.** This is the step that prevents 7-day refresh-token expiry. Click "Publish App" on the OAuth consent screen overview page. You don't need to submit for verification; the warning about unverified apps will appear but is harmless for personal use.
4. **Create OAuth credentials:**
   - APIs & Services → Credentials → Create credentials → OAuth client ID.
   - Application type: **Desktop app**.
   - Name: `weekly-digest local`.
   - Download the JSON (or just copy the client ID + secret).
5. **Add to `.env`:**
   ```
   GOOGLE_CLIENT_ID=<from step 4>
   GOOGLE_CLIENT_SECRET=<from step 4>
   ```
6. **Generate a refresh token:**
   ```bash
   uv run python scripts/generate_calendar_token.py
   ```
   A browser opens, you grant access, and the script prints the refresh token. Add it to `.env`:
   ```
   GOOGLE_REFRESH_TOKEN=<output of the script>
   ```
7. **Find your calendar IDs:**
   - In Google Calendar (web), click the gear icon → Settings.
   - For each calendar you want to include, click it in the sidebar, scroll to "Integrate calendar", copy the **Calendar ID**.
   - `primary` is a shortcut for "the main calendar of the authenticated account."
   ```
   GOOGLE_CALENDAR_IDS=primary,<shared.calendar.id>@group.calendar.google.com
   ```

## 3. Ticketmaster Discovery API

1. Sign up at https://developer-acct.ticketmaster.com/user/login.
2. Create a new app — name it `weekly-digest`. The default plan includes 5,000 calls/day, oversized for this use case.
3. Copy the consumer key:
   ```
   TICKETMASTER_API_KEY=<your key>
   ```

## 4. Happy hours & deals (no extra setup)

The "happy hours & deals" section uses Claude's server-side `web_search` tool, which is part of the Anthropic API you set up in section 6 below. **No separate provider account or API key.** Cost is roughly $0.01 per weekly run.

A previous version of this project used Yelp Fusion for a "restaurant of the week" pick. Yelp has gated new Fusion access since 2024 and the `special_hours` field is rarely populated anyway, so we replaced it with a Claude-driven web search that returns current happy hours, restaurant specials, and free/cheap local events with source URLs for attribution. See `docs/ARCHITECTURE.md` → "Deals via Claude web_search" for the reasoning.

## 5. Songkick (optional)

Songkick gates new API access and may not approve personal projects. If your access is denied, leave `SONGKICK_API_KEY` blank — the source no-ops gracefully.

1. Apply at https://www.songkick.com/api_key_requests/new.
2. If approved:
   ```
   SONGKICK_API_KEY=<your key>
   ```

## 6. Anthropic API

1. Sign up at https://console.anthropic.com.
2. Add a payment method (this project costs <$5/year but the API requires billing).
3. Create an API key:
   ```
   ANTHROPIC_API_KEY=<your key>
   ```

## 7. Resend

1. Sign up at https://resend.com.
2. **Verify a domain** (cleanest approach) OR use `onboarding@resend.dev` as the From for testing (only delivers to your own verified email).
   - To verify a domain, add the DNS records Resend shows you. Takes ~10 minutes.
3. Create an API key (Settings → API Keys):
   ```
   RESEND_API_KEY=<your key>
   NEWSLETTER_FROM_EMAIL=newsletter@yourdomain.com
   NEWSLETTER_TO_EMAILS=you@gmail.com,partner@gmail.com
   ```

## 8. First end-to-end test (local)

```bash
# Build the preference profile
uv run python -m newsletter.main --profile

# Render the newsletter to disk without sending
uv run python -m newsletter.main --weekly --dry-run
# → out/newsletter-<date>.html — open in Gmail (paste into a draft) to preview

# Send a real newsletter to yourself only
uv run python -m newsletter.main --weekly --to=you@gmail.com
```

## 9. GitHub Actions setup

1. Push to a new GitHub repo named `weekly-digest`.
2. Go to repo Settings → Secrets and variables → Actions → New repository secret.
3. Add each of these secrets (values from your `.env`):

   | Secret | Value |
   |---|---|
   | `GOOGLE_CLIENT_ID` | from step 2 |
   | `GOOGLE_CLIENT_SECRET` | from step 2 |
   | `GOOGLE_REFRESH_TOKEN` | from step 2 |
   | `GOOGLE_CALENDAR_IDS` | from step 2 |
   | `TICKETMASTER_API_KEY` | from step 3 |
   | `SONGKICK_API_KEY` | from step 5 (optional) |
   | `ANTHROPIC_API_KEY` | from step 6 |
   | `RESEND_API_KEY` | from step 7 |
   | `NEWSLETTER_FROM_EMAIL` | from step 7 |
   | `NEWSLETTER_TO_EMAILS` | from step 7 |
   | `FAILURE_NOTIFY_EMAIL` | (optional) — where to send alerts when the workflow fails. Defaults to `NEWSLETTER_FROM_EMAIL`. |

4. Trigger the workflows manually first (Actions → workflow → Run workflow) — verify both `monthly-profile` and `weekly-newsletter` complete green before letting the cron handle it.

## Rotating secrets

Plan for this — keys leak.

| Secret | How to rotate |
|---|---|
| `GOOGLE_REFRESH_TOKEN` | Re-run `scripts/generate_calendar_token.py`, update GitHub secret. |
| `GOOGLE_CLIENT_SECRET` | Reset in Cloud Console, update GitHub secret, re-generate refresh token (old one is invalidated). |
| `TICKETMASTER_API_KEY`, `SONGKICK_API_KEY` | Regenerate in the provider's dashboard, update GitHub secret. |
| `ANTHROPIC_API_KEY` | Delete + create new at console.anthropic.com, update GitHub secret. |
| `RESEND_API_KEY` | Delete + create new at resend.com, update GitHub secret. |

After rotating, trigger `weekly-newsletter.yml` manually via workflow_dispatch to confirm the new key works before the next scheduled run.

## Troubleshooting

**The weekly workflow runs but no email arrives.**
- Check the workflow's logs for `resend.send_ok` — it should include a `message_id`.
- Check the Resend dashboard for that message ID — if it shows "bounced" or "delivery failed", your From domain isn't verified.
- Check spam folders — first email from a new domain often lands there.

**Calendar fetch returns 401 or "invalid_grant".**
- Your refresh token has expired. Most common cause: the OAuth consent screen is still in Testing mode (7-day expiry). Publish to Production and re-run `scripts/generate_calendar_token.py`.

**Deals section is empty week after week.**
- Claude's `web_search` may legitimately fail to find current happy-hour info for a given week — Charlotte coverage on the open web varies. Check the workflow logs for `deals.fetch_done` with `picks=0`. If it's persistent (3+ weeks in a row), consider widening the prompt in `newsletter/sources/deals.py` or pinning `CLAUDE_DEALS_MODEL` to a stronger model.

**Claude API returns 400 for an unknown model.**
- Update `CLAUDE_PROFILE_MODEL` / `CLAUDE_RANKING_MODEL` in `.env` (or GitHub secrets). The defaults in `newsletter/config.py` track current model aliases.
