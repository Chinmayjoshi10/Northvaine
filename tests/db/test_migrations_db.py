"""Live round trip of migration 0002 against a real PostgreSQL (marked `db`)."""

from __future__ import annotations

import asyncio
import uuid

import pytest
from alembic import command
from sqlalchemy import pool, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from northvaine.core.db import normalize_database_url
from northvaine.core.standards import EMBED_DIM_EXPECTED
from tests.db.conftest import alembic_config

pytestmark = pytest.mark.db


async def _run(url: str, work) -> object:
    """Run `work(conn)` in one transaction on a throwaway engine."""
    normalized = normalize_database_url(url)
    engine = create_async_engine(
        normalized.url, connect_args=normalized.connect_args, poolclass=pool.NullPool
    )
    try:
        async with engine.begin() as conn:
            return await work(conn)
    finally:
        await engine.dispose()


def run(url: str, work) -> object:
    return asyncio.run(_run(url, work))


def test_upgrade_downgrade_upgrade_round_trip(migrated_url: str) -> None:
    cfg = alembic_config(migrated_url)
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")

    async def probe(conn: AsyncConnection) -> tuple[list[str], int, int, str]:
        ext = (await conn.execute(text("SELECT extname FROM pg_extension"))).scalars().all()
        concepts = (
            await conn.execute(text("SELECT count(*) FROM event_concepts WHERE level = 0"))
        ).scalar_one()
        views = (
            await conn.execute(
                text(
                    "SELECT count(*) FROM pg_views "
                    "WHERE viewname IN ('patterns', 'verified_claims')"
                )
            )
        ).scalar_one()
        embedding = (
            await conn.execute(
                text(
                    "SELECT format_type(atttypid, atttypmod) FROM pg_attribute "
                    "WHERE attrelid = 'theses'::regclass AND attname = 'embedding'"
                )
            )
        ).scalar_one()
        return list(ext), concepts, views, embedding

    extensions, concepts, views, embedding = run(migrated_url, probe)
    assert "vector" in extensions
    print("pgcrypto present:", "pgcrypto" in extensions)  # reported, not asserted
    assert concepts == 13  # 0002 seeds 12, 0007 adds imports_recorded (D102)
    assert views == 2
    # 0003 sizes the vectors (D7/D14): a round trip to base and back must end at the head's
    # shape, not M1's dimensionless one.
    assert embedding == f"vector({EMBED_DIM_EXPECTED})"


def test_event_concepts_has_thirteen_level_zero_rows(migrated_url: str) -> None:
    async def count(conn: AsyncConnection) -> int:
        result = await conn.execute(text("SELECT count(*) FROM event_concepts WHERE level = 0"))
        return result.scalar_one()

    assert run(migrated_url, count) == 13


def test_decision_propensity_must_be_in_zero_one(migrated_url: str) -> None:
    insert = text(
        "INSERT INTO decisions (kind, features, choice, propensity) "
        "VALUES ('brief', '{}', '{}', :p)"
    )

    async def zero(conn: AsyncConnection) -> None:
        await conn.execute(insert, {"p": 0})

    async def one(conn: AsyncConnection) -> None:
        await conn.execute(insert, {"p": 1})

    with pytest.raises(IntegrityError):
        run(migrated_url, zero)
    run(migrated_url, one)


def test_open_case_uniqueness_ignores_closed_cases(migrated_url: str) -> None:
    workspace, company = uuid.uuid4(), uuid.uuid4()

    async def seed(conn: AsyncConnection) -> None:
        await conn.execute(
            text("INSERT INTO workspaces (id, name) VALUES (:w, 'w')"), {"w": workspace}
        )
        await conn.execute(
            text("INSERT INTO companies (id, name) VALUES (:c, 'c')"), {"c": company}
        )

    run(migrated_url, seed)

    def add_case(stage: str):
        async def work(conn: AsyncConnection) -> None:
            await conn.execute(
                text(
                    "INSERT INTO cases (workspace_id, company_id, direction, stage) "
                    "VALUES (:w, :c, 'outbound', :s)"
                ),
                {"w": workspace, "c": company, "s": stage},
            )

        return work

    run(migrated_url, add_case("candidate"))
    with pytest.raises(IntegrityError):
        run(migrated_url, add_case("gated"))
    run(migrated_url, add_case("won"))
    run(migrated_url, add_case("won"))
