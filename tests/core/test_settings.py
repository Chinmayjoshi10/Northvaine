"""Settings: no env needed at import, secrets stay hidden, lookups are cached."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from northvaine.core import settings as settings_module
from northvaine.core.settings import (
    ConfigError,
    Settings,
    require_database_url,
    require_test_database_url,
)
from northvaine.core.settings import get_settings as real_get_settings
from northvaine.core.standards import EMBED_DIM_EXPECTED, validate_embed_dim

pytestmark = pytest.mark.usefixtures("clean_settings")

SECRETS = {
    "DATABASE_URL": "postgresql+asyncpg://u:hunter2-db-secret@h:5432/d",
    "NEBIUS_API_KEY": "nebius-secret-value-123",
    "TAVILY_API_KEY": "tavily-secret-value-456",
}


def test_constructs_with_no_env() -> None:
    s = Settings(_env_file=None)
    assert s.database_url is None
    assert s.model_fast is None
    assert s.embed_dim is None
    assert s.daily_budget_usd is None
    assert s.total_budget_usd is None
    assert s.run_budget_usd == Decimal("0.20")
    assert s.max_call_cost_usd == Decimal("0.05")
    assert s.llm_timeout_seconds == 30.0
    assert s.llm_max_retries == 2
    assert s.db_pool_mode == "session"
    assert s.job_max_attempts == 5


def test_money_caps_parse_as_decimal_not_float(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DAILY_BUDGET_USD", "1.00")
    monkeypatch.setenv("TOTAL_BUDGET_USD", "1.00")
    monkeypatch.setenv("RUN_BUDGET_USD", "0.10")
    monkeypatch.setenv("MAX_CALL_COST_USD", "0.02")
    s = Settings(_env_file=None)
    for value in (s.daily_budget_usd, s.total_budget_usd, s.run_budget_usd, s.max_call_cost_usd):
        assert isinstance(value, Decimal)
    assert s.daily_budget_usd == Decimal("1.00")
    assert s.total_budget_usd == Decimal("1.00")


def test_embed_dim_matching_expected_does_not_raise(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EMBED_DIM", str(EMBED_DIM_EXPECTED))
    settings_module.get_settings.cache_clear()
    validate_embed_dim(Settings(_env_file=None))


def test_embed_dim_mismatch_raises_config_error_naming_embed_dim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EMBED_DIM", str(EMBED_DIM_EXPECTED + 1))
    with pytest.raises(ConfigError, match="EMBED_DIM"):
        validate_embed_dim(Settings(_env_file=None))


def test_embed_dim_unset_does_not_raise() -> None:
    validate_embed_dim(Settings(_env_file=None))


def test_require_database_url_names_the_variable() -> None:
    with pytest.raises(ConfigError, match="DATABASE_URL"):
        require_database_url()
    with pytest.raises(ConfigError, match="TEST_DATABASE_URL"):
        require_test_database_url()


def test_require_database_url_returns_plain_string(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", SECRETS["DATABASE_URL"])
    assert require_database_url(Settings(_env_file=None)) == SECRETS["DATABASE_URL"]


def test_env_is_case_insensitive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("db_pool_mode", "transaction")
    monkeypatch.setenv("Job_Max_Attempts", "7")
    s = Settings(_env_file=None)
    assert s.db_pool_mode == "transaction"
    assert s.job_max_attempts == 7


def test_unknown_env_keys_are_ignored(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("NOT_A_NORTHVAINE_SETTING", "x")
    env_file = tmp_path / ".env"
    env_file.write_text("SOMETHING_ELSE=1\nDB_ECHO=true\n", encoding="utf-8")
    s = Settings(_env_file=env_file)
    assert s.db_echo is True
    assert not hasattr(s, "something_else")


def test_empty_env_var_falls_back_to_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JOB_LEASE_SECONDS", "")
    monkeypatch.setenv("EMBED_DIM", "")
    monkeypatch.setenv("DATABASE_URL", "")
    s = Settings(_env_file=None)
    assert s.job_lease_seconds == 300
    assert s.embed_dim is None
    assert s.database_url is None


def test_secrets_never_appear_in_repr_or_json(monkeypatch: pytest.MonkeyPatch) -> None:
    for name, value in SECRETS.items():
        monkeypatch.setenv(name, value)
    s = Settings(_env_file=None)
    rendered = [repr(s), str(s), s.model_dump_json()]
    for value in SECRETS.values():
        for text in rendered:
            assert value not in text
    assert s.nebius_api_key is not None
    assert s.nebius_api_key.get_secret_value() == SECRETS["NEBIUS_API_KEY"]


def test_get_settings_is_cached_and_cache_clear_resets(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)  # no developer .env
    get_settings = real_get_settings  # imported before clean_settings patched the module
    assert get_settings is not settings_module.get_settings
    get_settings.cache_clear()
    first = get_settings()
    assert get_settings() is first
    get_settings.cache_clear()
    assert get_settings() is not first
    get_settings.cache_clear()


def test_clean_settings_patches_get_settings() -> None:
    s = settings_module.get_settings()
    assert s.database_url is None
    assert settings_module.get_settings() is s
