"""The budget guard's real SQL against a real PostgreSQL (marked `db`, deselected from the gate).

The unit tests in tests/brain/test_budget.py use a fake executor and prove the *logic*. These
prove the two things a fake cannot: that the aggregates are valid SQL the database accepts, and
that `IS NOT DISTINCT FROM` really does bucket a NULL workspace separately (T2.3, D3).
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import pool, text
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from northvaine.brain.budget import DAY_SUM, TOTAL_SUM, RunContext, record_call, utc_day_bounds
from northvaine.core.db import normalize_database_url
from northvaine.core.models import LlmUsage

pytestmark = pytest.mark.db

USAGE = LlmUsage(input_tokens=100, output_tokens=20, total_tokens=120)


async def _run(url: str, work) -> object:
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


async def insert(conn: AsyncConnection, **over) -> None:
    """One llm_calls row through the real record_call path."""
    fields = {
        "model": "nvidia/Nemotron-3_5-Lightning",
        "purpose": "test",
        "usage": USAGE,
        "cost_usd": Decimal("0.01"),
        "ok": True,
        "error": None,
        "latency_ms": 10,
    }
    fields.update(over)
    ctx = fields.pop("run", None) or RunContext(workspace_id=fields.pop("workspace_id", None))
    await record_call(ctx, session=conn, **fields)


def test_record_call_writes_a_real_row(migrated_url: str) -> None:
    async def work(conn: AsyncConnection) -> dict[str, object]:
        run_ctx = RunContext()
        await record_call(
            run_ctx,
            session=conn,
            model="nvidia/Nemotron-3_5-Lightning",
            purpose="smoke",
            usage=USAGE,
            cost_usd=Decimal("0.000123"),
            ok=True,
            error=None,
            latency_ms=42,
            prompt_version="smoke_ping.v1",
        )
        row = (
            await conn.execute(
                text(
                    "SELECT model, purpose, input_tokens, output_tokens, cost_usd, ok, "
                    "run_id, prompt_version, latency_ms, error, provider FROM llm_calls"
                )
            )
        ).mappings().one()
        return dict(row)

    row = run(migrated_url, work)
    assert row["purpose"] == "smoke"
    assert row["input_tokens"] == 100
    assert row["cost_usd"] == Decimal("0.000123")
    assert row["ok"] is True
    assert row["prompt_version"] == "smoke_ping.v1"
    assert row["latency_ms"] == 42
    assert row["error"] is None
    assert row["provider"] == "nebius"  # D15: the default applies without being passed


def test_a_failed_attempt_records_zero_cost_and_null_tokens(migrated_url: str) -> None:
    async def work(conn: AsyncConnection) -> dict[str, object]:
        await record_call(
            RunContext(),
            session=conn,
            model="m",
            purpose="p",
            usage=None,
            cost_usd=Decimal("0.05"),  # the caller's estimate must not reach the ledger
            ok=False,
            error="timeout after 30s",
            latency_ms=30_000,
        )
        row = (
            await conn.execute(
                text("SELECT cost_usd, ok, input_tokens, error FROM llm_calls")
            )
        ).mappings().one()
        return dict(row)

    row = run(migrated_url, work)
    assert row["cost_usd"] == Decimal("0")
    assert row["ok"] is False
    assert row["input_tokens"] is None
    assert row["error"] == "timeout after 30s"


def test_the_day_sum_buckets_null_workspace_separately(migrated_url: str) -> None:
    """D3: `workspace_id IS NULL` is its own bucket - what onboarding and smoke calls use."""
    workspace = uuid.uuid4()

    async def work(conn: AsyncConnection) -> tuple[Decimal, Decimal]:
        await insert(conn, workspace_id=workspace, cost_usd=Decimal("0.70"))
        await insert(conn, workspace_id=None, cost_usd=Decimal("0.05"))

        start, end = utc_day_bounds()
        params = {"start": start, "end": end}
        named = await conn.execute(text(DAY_SUM), {**params, "workspace_id": workspace})
        anon = await conn.execute(text(DAY_SUM), {**params, "workspace_id": None})
        return Decimal(str(named.scalar_one())), Decimal(str(anon.scalar_one()))

    named, anon = run(migrated_url, work)
    assert named == Decimal("0.70")
    assert anon == Decimal("0.05")


def test_the_day_sum_excludes_yesterday(migrated_url: str) -> None:
    async def work(conn: AsyncConnection) -> tuple[Decimal, Decimal]:
        await insert(conn, workspace_id=None, cost_usd=Decimal("0.03"))
        # A row stamped just before today's UTC midnight must not count toward today.
        start, end = utc_day_bounds()
        await conn.execute(
            text(
                "INSERT INTO llm_calls (model, purpose, cost_usd, ok, provider, created_at) "
                "VALUES ('m', 'yesterday', 1.00, true, 'nebius', :at)"
            ),
            {"at": start - timedelta(seconds=1)},
        )
        today = await conn.execute(
            text(DAY_SUM), {"start": start, "end": end, "workspace_id": None}
        )
        total = await conn.execute(text(TOTAL_SUM))
        return Decimal(str(today.scalar_one())), Decimal(str(total.scalar_one()))

    today, total = run(migrated_url, work)
    assert today == Decimal("0.03")
    assert total == Decimal("1.03")  # the lifetime cap has no date filter


def test_the_lifetime_sum_spans_every_workspace(migrated_url: str) -> None:
    async def work(conn: AsyncConnection) -> Decimal:
        await insert(conn, workspace_id=uuid.uuid4(), cost_usd=Decimal("0.10"))
        await insert(conn, workspace_id=uuid.uuid4(), cost_usd=Decimal("0.20"))
        await insert(conn, workspace_id=None, cost_usd=Decimal("0.30"))
        result = await conn.execute(text(TOTAL_SUM))
        return Decimal(str(result.scalar_one()))

    assert run(migrated_url, work) == Decimal("0.60")


def test_the_sums_are_zero_not_null_on_an_empty_table(migrated_url: str) -> None:
    """COALESCE matters: a NULL sum compared against a cap would raise, not stop the call."""

    async def work(conn: AsyncConnection) -> tuple[object, object]:
        start, end = utc_day_bounds(datetime.now(UTC))
        day = await conn.execute(
            text(DAY_SUM), {"start": start, "end": end, "workspace_id": None}
        )
        total = await conn.execute(text(TOTAL_SUM))
        return day.scalar_one(), total.scalar_one()

    day, total = run(migrated_url, work)
    assert Decimal(str(day)) == Decimal("0")
    assert Decimal(str(total)) == Decimal("0")
