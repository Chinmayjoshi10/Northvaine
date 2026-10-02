"""Database fixtures for tests marked `db` (frozen M1 contract, factory/board/M1/PLAN.md).

`migrated_url` is a sync fixture: the async migrations/env.py calls `asyncio.run`, which
fails inside a running event loop.

- `test_db_isolation = "database"`: create `nv_test_<uuid4 hex[:12]>` from TEST_DATABASE_URL,
  upgrade it to head, yield its URL, then drop the database. Dropping a whole database (not a
  schema) never touches the database-wide extensions other runs rely on.
- `test_db_isolation = "reuse"` (a Neon branch, or a role without CREATEDB): downgrade
  TEST_DATABASE_URL to base, upgrade to head, yield it, and downgrade to base on teardown.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

from northvaine.core import settings as settings_module

ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = ROOT / "alembic.ini"


def alembic_config(url: str) -> Config:
    """An Alembic Config for the repo, pointed at `url` (no ini interpolation of the URL)."""
    cfg = Config(str(ALEMBIC_INI))
    cfg.attributes["url"] = url
    return cfg


def per_run_database_name() -> str:
    return f"nv_test_{uuid.uuid4().hex[:12]}"


def with_database(raw_url: str, database: str) -> str:
    """Return `raw_url` with its database name replaced, keeping the query string."""
    from sqlalchemy.engine import make_url

    return make_url(raw_url).set(database=database).render_as_string(hide_password=False)


async def _admin_execute(raw_url: str, sql: str) -> None:
    from sqlalchemy import pool, text
    from sqlalchemy.ext.asyncio import create_async_engine

    from northvaine.core.db import normalize_database_url

    normalized = normalize_database_url(raw_url)
    engine = create_async_engine(
        normalized.url,
        connect_args=normalized.connect_args,
        poolclass=pool.NullPool,
        isolation_level="AUTOCOMMIT",
    )
    try:
        async with engine.connect() as conn:
            await conn.execute(text(sql))
    finally:
        await engine.dispose()


@pytest.fixture
def migrated_url(test_database_url: str) -> Iterator[str]:
    """The URL of a database migrated to `head`; skips without TEST_DATABASE_URL."""
    mode = settings_module.get_settings().test_db_isolation
    if mode == "reuse":
        cfg = alembic_config(test_database_url)
        command.downgrade(cfg, "base")
        command.upgrade(cfg, "head")
        try:
            yield test_database_url
        finally:
            command.downgrade(cfg, "base")
        return

    name = per_run_database_name()
    asyncio.run(_admin_execute(test_database_url, f'CREATE DATABASE "{name}"'))
    try:
        url = with_database(test_database_url, name)
        command.upgrade(alembic_config(url), "head")
        yield url
    finally:
        drop = f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'
        asyncio.run(_admin_execute(test_database_url, drop))
