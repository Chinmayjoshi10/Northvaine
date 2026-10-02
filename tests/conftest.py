"""Shared test fixtures (frozen M1 contract, see factory/board/M1/PLAN.md)."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from functools import lru_cache

import pytest
import pytest_asyncio

from northvaine.core import settings as settings_module
from northvaine.core.settings import ConfigError, Settings, require_test_database_url

pytest_plugins = ["pytester"]


@pytest.fixture
def clean_settings(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """No Settings env vars and no `.env`: `get_settings()` returns pure defaults.

    Tests may still `monkeypatch.setenv(...)`; call `get_settings.cache_clear()` after that.
    """
    for name in Settings.model_fields:
        monkeypatch.delenv(name.upper(), raising=False)
        monkeypatch.delenv(name, raising=False)
    settings_module.get_settings.cache_clear()
    patched = lru_cache(maxsize=1)(lambda: Settings(_env_file=None))
    monkeypatch.setattr(settings_module, "get_settings", patched)
    yield
    patched.cache_clear()
    monkeypatch.undo()
    settings_module.get_settings.cache_clear()


@pytest.fixture
def test_database_url() -> str:
    """TEST_DATABASE_URL as a string; skips the test when it is not set."""
    try:
        return require_test_database_url()
    except ConfigError:
        pytest.skip("db: set TEST_DATABASE_URL")


@pytest_asyncio.fixture(autouse=True)
async def _dispose_engine_after_db_test(request: pytest.FixtureRequest) -> AsyncIterator[None]:
    """For tests marked `db` only: require TEST_DATABASE_URL, then dispose the engine.

    Disposing in teardown means no engine is reused across event loops.
    """
    if request.node.get_closest_marker("db") is None:
        yield
        return
    request.getfixturevalue("test_database_url")
    yield
    from northvaine.core.db import dispose_engine

    await dispose_engine()
