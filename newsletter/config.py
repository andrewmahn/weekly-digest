from pathlib import Path
from typing import Annotated

from pydantic import EmailStr, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


def _csv_list(raw: str) -> list[str]:
    return [item.strip() for item in raw.split(",") if item.strip()]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    google_client_id: SecretStr
    google_client_secret: SecretStr
    google_refresh_token: SecretStr
    google_calendar_ids: str = "primary"

    ticketmaster_api_key: SecretStr
    songkick_api_key: SecretStr | None = None

    anthropic_api_key: SecretStr
    claude_profile_model: str = "claude-haiku-4-5"
    claude_ranking_model: str = "claude-sonnet-4-6"

    resend_api_key: SecretStr
    newsletter_from_email: EmailStr
    newsletter_to_emails: str

    city_name: str = "Charlotte"
    city_state: str = "NC"
    city_lat: float = 35.2271
    city_lon: float = -80.8431
    timezone: str = "America/New_York"

    @property
    def calendar_id_list(self) -> list[str]:
        return _csv_list(self.google_calendar_ids)

    @property
    def recipient_list(self) -> list[str]:
        return _csv_list(self.newsletter_to_emails)


PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = PROJECT_ROOT / "data"
OUT_DIR = PROJECT_ROOT / "out"
PREFERENCES_PATH = DATA_DIR / "preferences.json"


def load_settings() -> Settings:
    """Load settings from environment / .env. Fails fast on missing required vars."""
    return Settings()  # type: ignore[call-arg]


CitySetting = Annotated[
    str,
    Field(
        description="City name for event filtering and weather lookup.",
    ),
]
