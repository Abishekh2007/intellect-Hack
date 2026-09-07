"""Application configuration via pydantic-settings.

All secrets come from a local `.env` file or environment variables. Never
hardcode API keys. Keys are resolved server-side only and never sent to
the browser.
"""

from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        # Fields with a validation_alias (bedrock_api_key) are otherwise
        # settable only by that alias, so `Settings(bedrock_api_key=...)` --
        # the shape the tests and callers use everywhere else -- would be
        # silently dropped.
        populate_by_name=True,
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
    # Rows a query may return. `hard_row_ceiling` is the absolute cap the SQL
    # guard enforces; `max_query_rows` is the default LIMIT injected when the
    # query names none. Both were documented in .env.example, but only the
    # ceiling was ever read — setting MAX_QUERY_ROWS did nothing at all.
    max_query_rows: int = 500
    hard_row_ceiling: int = 1000

    # --- LLM providers (all optional; any present key is used) ---
    llm_provider: str = "bedrock"  # priority order is managed by failover
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.0-flash"
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    openai_base_url: str | None = None
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-opus-5"
    # Amazon Bedrock, reached with a Bedrock API key (bearer token) rather
    # than SigV4 credentials. AWS's own docs export the key as
    # AWS_BEARER_TOKEN_BEDROCK, so that name is accepted too.
    bedrock_api_key: str = Field(
        default="", validation_alias=AliasChoices("BEDROCK_API_KEY", "AWS_BEARER_TOKEN_BEDROCK")
    )
    bedrock_model: str = "qwen.qwen3-next-80b-a3b"
    bedrock_region: str = "us-east-1"

    # --- Rate limiting ---
    llm_rpm: int = 10  # requests per minute, sliding window

    # --- Sessions / storage ---
    session_ttl_seconds: int = 60 * 60 * 24  # 24h
    max_history_turns: int = 6

    @field_validator("db_path")
    @classmethod
    def _anchor_db_path(cls, value: Path) -> Path:
        """Resolve a relative DB_PATH against this file, not the CWD.

        `.env.example` ships `DB_PATH=data/ecommerce.db`, described as
        "relative to this file". Pydantic hands that through as-is, so it
        resolved against the working directory instead: launching the server
        from anywhere but `backend/` silently created and seeded an empty
        database somewhere else, and the demo data appeared to vanish.
        """
        value = Path(value)
        return value if value.is_absolute() else (BASE_DIR / value).resolve()

    @property
    def has_any_llm_key(self) -> bool:
        return any(
            self._is_real_key(k)
            for k in (
                self.gemini_api_key,
                self.openai_api_key,
                self.anthropic_api_key,
                self.bedrock_api_key,
            )
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