"""The migrated database must match schema.sql (T1.8; marked `db`, needs TEST_DATABASE_URL).

information_schema is the authority: tables, columns and nullability equal what
tests/core/ddl_parser.py reads from schema.sql.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from sqlalchemy import pool, text
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from northvaine.core.db import normalize_database_url
from tests.core.ddl_parser import parse_ddl

pytestmark = pytest.mark.db

SCHEMA = Path(__file__).resolve().parents[2] / "schema.sql"


async def _run(url: str, work):  # type: ignore[no-untyped-def]
    normalized = normalize_database_url(url)
    engine = create_async_engine(
        normalized.url, connect_args=normalized.connect_args, poolclass=pool.NullPool
    )
    try:
        async with engine.connect() as conn:
            return await work(conn)
    finally:
        await engine.dispose()


def run(url: str, work):  # type: ignore[no-untyped-def]
    return asyncio.run(_run(url, work))


def _expected() -> dict[str, dict[str, bool]]:
    tables = parse_ddl(SCHEMA.read_text(encoding="utf-8"))
    return {t: {c: info.nullable for c, info in cols.items()} for t, cols in tables.items()}


def test_tables_columns_and_nullability_equal_schema_sql(migrated_url: str) -> None:
    async def probe(conn: AsyncConnection) -> dict[str, dict[str, bool]]:
        rows = await conn.execute(
            text(
                "SELECT c.table_name, c.column_name, c.is_nullable "
                "FROM information_schema.columns c "
                "JOIN information_schema.tables t "
                "  ON t.table_schema = c.table_schema AND t.table_name = c.table_name "
                "WHERE c.table_schema = current_schema() AND t.table_type = 'BASE TABLE'"
            )
        )
        found: dict[str, dict[str, bool]] = {}
        for table, column, nullable in rows:
            found.setdefault(table, {})[column] = nullable == "YES"
        return found

    live = run(migrated_url, probe)
    live.pop("alembic_version", None)
    expected = _expected()
    assert set(live) == set(expected)
    for table in sorted(expected):
        assert live[table] == expected[table], table


def test_patterns_view_exists(migrated_url: str) -> None:
    async def probe(conn: AsyncConnection) -> list[str]:
        rows = await conn.execute(
            text(
                "SELECT table_name FROM information_schema.views "
                "WHERE table_schema = current_schema()"
            )
        )
        return [r[0] for r in rows]

    assert run(migrated_url, probe) == ["patterns"]


def test_vector_columns_are_dimensionless(migrated_url: str) -> None:
    async def probe(conn: AsyncConnection) -> dict[str, int]:
        rows = await conn.execute(
            text(
                "SELECT cl.relname || '.' || a.attname, a.atttypmod "
                "FROM pg_attribute a "
                "JOIN pg_class cl ON cl.oid = a.attrelid "
                "JOIN pg_namespace n ON n.oid = cl.relnamespace "
                "JOIN pg_type ty ON ty.oid = a.atttypid "
                "WHERE ty.typname = 'vector' AND a.attnum > 0 AND NOT a.attisdropped "
                "AND cl.relkind = 'r' AND n.nspname = current_schema()"
            )
        )
        return {name: typmod for name, typmod in rows}

    vectors = run(migrated_url, probe)
    schema_vectors = {
        f"{table}.{column}"
        for table, cols in parse_ddl(SCHEMA.read_text(encoding="utf-8")).items()
        for column, info in cols.items()
        if info.type.startswith("vector")
    }
    assert set(vectors) == schema_vectors
    assert schema_vectors  # the check must not pass on an empty set
    assert set(vectors.values()) == {-1}, vectors
