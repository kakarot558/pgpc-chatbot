"""Central configuration. Every tunable value lives here and is read from .env."""
from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]
SQLITE_PREFIX = "sqlite:///"


class Settings(BaseSettings):
    app_name: str = "PGPC SmartGuide"
    debug: bool = False
    database_url: str = "sqlite:///./pgpc_smartguide.db"
    secret_key: str = "change-me"
    access_token_expire_minutes: int = 60
    openai_api_key: str = ""
    llm_model: str = ""
    similarity_threshold: float = 0.35
    high_confidence_threshold: float = 0.80
    medium_confidence_threshold: float = 0.60
    session_expire_minutes: int = 60
    max_session_messages: int = 100      # messages (both sides) kept in one chat session
    followup_window: int = 10            # how many recent answers are searched for the "topic"
    chat_retention_days: int = 30        # expired sessions older than this can be purged by an admin
    max_upload_size_mb: int = 10
    max_question_chars: int = 500
    spelling_cutoff: float = 0.85
    intent_min_confidence: float = 0.35
    # Official online enrollment page. "How do I enroll?" is answered with this link (empty = feature off).
    enrollment_url: str = "https://pgpclaunch.padregarcia.gov.ph/"
    admin_username: str = "admin"
    admin_email: str = ""
    admin_password: str = ""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @field_validator("database_url")
    @classmethod
    def anchor_sqlite_file(cls, url: str) -> str:
        """A relative SQLite path ("sqlite:///./x.db") is anchored to the project folder, so the same
        database file is used no matter which folder the server or a script is started from.
        In-memory ("sqlite://") and absolute paths are left alone."""
        if url.startswith(SQLITE_PREFIX):
            path = url[len(SQLITE_PREFIX):]
            if path and path != ":memory:" and not Path(path).is_absolute() and not path.startswith("/"):
                return SQLITE_PREFIX + (ROOT / path).as_posix()
        return url


@lru_cache
def get_settings() -> Settings:
    return Settings()
