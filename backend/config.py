"""Application configuration via pydantic-settings.

All secrets come from a local `.env` file or environment variables. Never
hardcode API keys. Keys are resolved server-side only and never sent to
the browser.
"""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- App ---
    app_name: str = "DataPilot AI"
    cors_origins: list[str] = [
        "http://localhost:3000",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]

    # --- Database ---
    db_path: Path = BASE_DIR / "data" / "ecommerce.db"
    max_query_rows: int = 500
    hard_row_ceiling: int = 1000

    # --- LLM providers (all optional; any present key is used) ---
    llm_provider: str = "gemini"  # priority order is managed by failover
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.0-flash"
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    openai_base_url: str | None = None
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-3-5-sonnet-20241022"

    # --- Rate limiting ---
    llm_rpm: int = 10  # requests per minute, sliding window

    # --- Sessions / storage ---
    session_ttl_seconds: int = 60 * 60 * 24  # 24h
    max_history_turns: int = 6

    @property
    def has_any_llm_key(self) -> bool:
        return any(
            self._is_real_key(k)
            for k in (self.gemini_api_key, self.openai_api_key, self.anthropic_api_key)
        )

    @staticmethod
    def _is_real_key(key: str) -> bool:
        key = key.strip()
        if not key:
            return False
        lowered = key.lower()
        placeholders = (
            "your_",
            "xxx",
            "sk-xxx",
            "none",
            "null",
            "changeme",
            "put",
        )
        return not any(p in lowered for p in placeholders)


@lru_cache
def get_settings() -> Settings:
    return Settings()