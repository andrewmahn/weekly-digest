"""One-time helper: generate a Google Calendar OAuth refresh token.

Run locally (NOT in CI). Requirements:
1. A Google Cloud project with the Calendar API enabled.
2. An OAuth 2.0 client credential of type "Desktop app".
3. The OAuth consent screen **published to Production**. (Testing-mode refresh tokens
   expire after 7 days, which breaks the weekly cron.)
4. `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` set in your environment or .env.

Usage:
    uv run python scripts/generate_calendar_token.py

The script opens a browser, walks you through Google's OAuth consent, then prints the
refresh token. Add it to your `.env` (and to GitHub Actions secrets) as
`GOOGLE_REFRESH_TOKEN`.
"""

from __future__ import annotations

import os
import sys

from dotenv import load_dotenv
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]


def main() -> int:
    load_dotenv()

    client_id = os.getenv("GOOGLE_CLIENT_ID")
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET")
    if not client_id or not client_secret:
        sys.stderr.write(
            "GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET must be set in your environment or .env.\n"
            "Create an OAuth 2.0 Desktop-app client in Google Cloud Console first.\n"
        )
        return 2

    client_config = {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"],
        }
    }

    print("Opening browser for Google consent…")
    flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
    creds = flow.run_local_server(port=0, prompt="consent", access_type="offline")

    if not creds.refresh_token:
        sys.stderr.write(
            "No refresh token returned. This usually means the consent screen is in Testing mode.\n"
            "Publish the consent screen to Production and try again.\n"
        )
        return 1

    print("\n" + "=" * 64)
    print("SUCCESS — add this to your .env and to GitHub Actions secrets:")
    print("=" * 64)
    print(f"GOOGLE_REFRESH_TOKEN={creds.refresh_token}")
    print("=" * 64)

    print("\nNext: list your calendar IDs to populate GOOGLE_CALENDAR_IDS.")
    print("  - 'primary' reads the authenticated account's main calendar.")
    print("  - For shared calendars, find the ID in Google Calendar →")
    print("    Settings and sharing → Integrate calendar → Calendar ID.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
