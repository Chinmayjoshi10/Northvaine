"""Typed settings read from the environment and an optional `.env` file.

Nothing here needs a database URL or an API key at import. Secrets are SecretStr, so they
never appear in repr, logs or JSON dumps. Model ids, the Nebius base URL, EMBED_DIM and the
daily and total budgets have no defaults: they are confirmed in milestone 2 (docs/integrations/).
"""

from __future__ import annotations

from decimal import Decimal
from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class ConfigError(RuntimeError):
    """A required setting is missing or invalid; message names the variable."""


class Settings(BaseSettings):
    """Application settings. Env vars win over `.env`; unknown keys are ignored."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        env_ignore_empty=True,
        case_sensitive=False,
    )

    # database
    database_url: SecretStr | None = None
    test_database_url: SecretStr | None = None
    db_pool_mode: Literal["session", "transaction"] = "session"
    db_pool_size: int = Field(default=5, ge=1)
    db_max_overflow: int = Field(default=10, ge=0)
    db_echo: bool = False
    test_db_isolation: Literal["database", "reuse"] = "database"

    # LLM + sensors (values confirmed in M2; no defaults, no guesses)
    nebius_api_key: SecretStr | None = None
    nebius_base_url: str | None = None
    model_fast: str | None = None
    model_mid: str | None = None
    model_deep: str | None = None
    model_embed: str | None = None
    embed_dim: int | None = Field(default=None, ge=1)
    tavily_api_key: SecretStr | None = None

    # money caps (brain/budget.py checks all four before every call). DAILY_BUDGET_USD and
    # TOTAL_BUDGET_USD have no default: calls refuse to run until the founder sets both
    # (DECISIONS D1). RUN_BUDGET_USD and MAX_CALL_COST_USD get conservative defaults, since a
    # run cap with no default would block every run.
    daily_budget_usd: Decimal | None = None
    total_budget_usd: Decimal | None = None
    run_budget_usd: Decimal = Field(default=Decimal("0.20"), gt=0)
    max_call_cost_usd: Decimal = Field(default=Decimal("0.05"), gt=0)

    # LLM call behaviour
    llm_timeout_seconds: float = Field(default=30.0, gt=0)
    llm_max_retries: int = Field(default=2, ge=0)

    # queue
    job_lease_seconds: int = Field(default=300, ge=1)
    job_max_attempts: int = Field(default=5, ge=1)
    job_backoff_base_seconds: float = 30.0
    job_backoff_max_seconds: float = 3600.0


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings. Tests reset it with `get_settings.cache_clear()`."""
    return Settings()


def require_database_url(settings: Settings | None = None) -> str:
    """Return DATABASE_URL as a plain string, or raise ConfigError if it is not set."""
    value = (settings or get_settings()).database_url
    if value is None or not value.get_secret_value():
        raise ConfigError("DATABASE_URL is not set (see .env.example)")
    return value.get_secret_value()


def require_test_database_url(settings: Settings | None = None) -> str:
    """Return TEST_DATABASE_URL as a plain string, or raise ConfigError if it is not set."""
    value = (settings or get_settings()).test_database_url
    if value is None or not value.get_secret_value():
        raise ConfigError("TEST_DATABASE_URL is not set (see .env.example)")
    return value.get_secret_value()
