"""Database fixtures for tests marked `db` (frozen M1 contract, factory/board/M1/PLAN.md).

`migrated_url` is a sync fixture: the async migrations/env.py calls `asyncio.run`, which
fails inside a running event loop.

- `test_db_isolation = "database"`: create `nv_test_<uuid4 hex[:12]>` from TEST_DATABASE_URL,
  upgrade it to head, yield its URL, then drop the database. Dropping a whole database (not a
  schema) never touches the database-wide extensions other runs rely on.
- `test_db_isolation = "reuse"` (a Neon branch, or a role without CREATEDB): migrate
  TEST_DATABASE_URL to head **once per process**, then TRUNCATE every table before each test.
  Each test still starts with empty tables, but the schema is built once instead of once per
  test - which is where the ~12 minutes M1 measured actually went (T2.1b).
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import pool, text
from sqlalchemy.ext.asyncio import create_async_engine

from northvaine.core import settings as settings_module
from northvaine.core.db import normalize_database_url

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


_MIGRATED: set[str] = set()


def _session_migrated(url: str) -> None:
    """Bring `url` to head once per process."""
    cfg = alembic_config(url)
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    _MIGRATED.add(url)


_SEED: dict[str, list[dict[str, object]]] = {}


async def _capture_seed(url: str) -> None:
    """Remember the rows the migrations insert, so TRUNCATE can put them back.

    Migration 0002 seeds `event_concepts` with twelve level-0 rows. Truncating them away made
    `test_event_concepts_has_twelve_level_zero_rows` fail - the reuse mode had quietly traded
    away more than per-test isolation, it had changed what "migrated to head" means. Anything
    non-empty straight after a migration is seed data and is restored after every truncate.
    """
    normalized = normalize_database_url(url)
    engine = create_async_engine(
        normalized.url, connect_args=normalized.connect_args, poolclass=pool.NullPool
    )
    try:
        async with engine.begin() as conn:
            rows = await conn.execute(
                text(
                    "SELECT tablename FROM pg_tables "
                    "WHERE schemaname = current_schema() AND tablename <> 'alembic_version'"
                )
            )
            for (table,) in rows.all():
                present = (
                    await conn.execute(text(f'SELECT * FROM "{table}"'))
                ).mappings().all()
                if present:
                    _SEED[table] = [dict(row) for row in present]
    finally:
        await engine.dispose()


async def _restore_seed(conn: object) -> None:
    for table, rows in _SEED.items():
        for row in rows:
            columns = ", ".join(f'"{c}"' for c in row)
            placeholders = ", ".join(f":{c}" for c in row)
            await conn.execute(  # type: ignore[attr-defined]
                text(f'INSERT INTO "{table}" ({columns}) VALUES ({placeholders})'),
                row,
            )


async def _truncate_all(url: str) -> None:
    """Empty every table, then put the migrations' seed rows back.

    This is what replaces the per-test migration cycle. Each test still starts from the same
    state a fresh migration would give it - empty tables plus the seed - but the schema is built
    once instead of once per test, which is where the ~12 minutes went. The randomized-order run
    in the ticket report is what proves no leakage was introduced.
    """
    normalized = normalize_database_url(url)
    engine = create_async_engine(
        normalized.url, connect_args=normalized.connect_args, poolclass=pool.NullPool
    )
    try:
        async with engine.begin() as conn:
            rows = await conn.execute(
                text(
                    "SELECT tablename FROM pg_tables "
                    "WHERE schemaname = current_schema() AND tablename <> 'alembic_version'"
                )
            )
            tables = [f'"{r[0]}"' for r in rows]
            if tables:
                await conn.execute(
                    text(f"TRUNCATE {', '.join(tables)} RESTART IDENTITY CASCADE")
                )
            await _restore_seed(conn)
    finally:
        await engine.dispose()


@pytest.fixture
def migrated_url(test_database_url: str) -> Iterator[str]:
    """The URL of a database migrated to `head`; skips without TEST_DATABASE_URL."""
    mode = settings_module.get_settings().test_db_isolation
    if mode == "reuse":
        # Migrate once for the whole session (the session fixture below), then hand each test a
        # truncated database. A downgrade-to-base and re-upgrade per test is what made db-test
        # take ~12 minutes against Neon: the cost is in the DDL, not the data.
        if test_database_url not in _MIGRATED:
            _session_migrated(test_database_url)
            asyncio.run(_capture_seed(test_database_url))
        asyncio.run(_truncate_all(test_database_url))
        yield test_database_url
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
