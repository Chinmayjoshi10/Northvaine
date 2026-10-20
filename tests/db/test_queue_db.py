"""Live queue checks against a migrated database (T1.7). Marked `db`."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import timedelta

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from northvaine.core import db, queue
from northvaine.core.models import JobStatus, NewJob

pytestmark = pytest.mark.db


@pytest_asyncio.fixture
async def maker(migrated_url: str) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine: AsyncEngine = db.create_engine(migrated_url)
    try:
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()


async def enqueue_n(maker: async_sessionmaker[AsyncSession], n: int, **kw: object) -> list[int]:
    async with maker() as s:
        ids = [await queue.enqueue(s, NewJob(kind="k", payload={"i": i}, **kw)) for i in range(n)]  # type: ignore[arg-type]
        await s.commit()
    return ids


async def row(maker: async_sessionmaker[AsyncSession], job_id: int) -> dict[str, object]:
    async with maker() as s:
        r = await s.execute(text("SELECT * FROM jobs WHERE id = :i"), {"i": job_id})
        return dict(r.mappings().one())


async def test_claim_plan_uses_initplan(maker: async_sessionmaker[AsyncSession]) -> None:
    from sqlalchemy.dialects import postgresql

    stmt = queue._claim_statement("w1")
    sql = str(stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
    async with maker() as s:
        plan = "\n".join((await s.execute(text("EXPLAIN (VERBOSE) " + sql))).scalars())
        await s.rollback()
    assert "InitPlan" in plan


async def test_two_claimers_never_share_a_job(maker: async_sessionmaker[AsyncSession]) -> None:
    ids = await enqueue_n(maker, 20)
    claimed: dict[str, list[int]] = {"a": [], "b": []}

    async def claimer(name: str) -> None:
        while True:
            async with maker() as s:
                job = await queue.claim(s, name)
                await s.commit()
            if job is None:
                return
            claimed[name].append(job.id)
            await asyncio.sleep(0)

    await asyncio.gather(claimer("a"), claimer("b"))
    everything = claimed["a"] + claimed["b"]
    assert len(everything) == len(set(everything)) == 20
    assert set(everything) == set(ids)


async def test_retry_with_backoff_then_terminal_failure(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    (job_id,) = await _one(maker, max_attempts=2)
    async with maker() as s:
        job = await queue.claim(s, "w")
        assert job is not None
        assert job.attempts == 1
        assert await queue.fail(s, job_id, "w", "first")
        await s.commit()
    r = await row(maker, job_id)
    assert r["status"] == "queued"
    assert r["locked_by"] is None and r["locked_at"] is None
    assert r["error"] == "first"
    async with maker() as s:
        wait = (
            await s.execute(text("SELECT run_after - now() FROM jobs WHERE id = :i"), {"i": job_id})
        ).scalar_one()
        assert timedelta(seconds=20) < wait <= timedelta(seconds=30)
        assert await queue.claim(s, "w") is None  # not ready yet
        await s.execute(text("UPDATE jobs SET run_after = now() WHERE id = :i"), {"i": job_id})
        job = await queue.claim(s, "w")
        assert job is not None
        assert job.attempts == 2
        assert await queue.fail(s, job_id, "w", "second")
        await s.commit()
    r = await row(maker, job_id)
    assert r["status"] == JobStatus.FAILED.value
    assert r["finished_at"] is not None
    assert r["error"] == "second"


async def test_non_owner_cannot_complete(maker: async_sessionmaker[AsyncSession]) -> None:
    (job_id,) = await _one(maker)
    async with maker() as s:
        assert await queue.claim(s, "owner") is not None
        await s.commit()
    before = await row(maker, job_id)
    async with maker() as s:
        assert await queue.complete(s, job_id, "intruder") is False
        assert await queue.fail(s, job_id, "intruder", "x") is False
        assert await queue.heartbeat(s, job_id, "intruder") is False
        await s.commit()
    assert await row(maker, job_id) == before
    async with maker() as s:
        assert await queue.complete(s, job_id, "owner") is True
        await s.commit()
    assert (await row(maker, job_id))["status"] == "done"


async def test_stale_leases_requeued_or_failed(maker: async_sessionmaker[AsyncSession]) -> None:
    retry, exhausted = await enqueue_n(maker, 1), await enqueue_n(maker, 1, max_attempts=1)
    async with maker() as s:
        assert await queue.claim(s, "w") is not None
        assert await queue.claim(s, "w") is not None
        await s.execute(text("UPDATE jobs SET locked_at = now() - interval '1 hour'"))
        result = await queue.requeue_stale(s, 300)
        await s.commit()
    assert result == queue.StaleResult(requeued=1, failed=1)
    r1, r2 = await row(maker, retry[0]), await row(maker, exhausted[0])
    assert r1["status"] == "queued" and r1["locked_by"] is None
    assert r2["status"] == "failed" and r2["error"] == "lease expired"


async def test_heartbeat_prevents_requeue(maker: async_sessionmaker[AsyncSession]) -> None:
    (job_id,) = await _one(maker)
    async with maker() as s:
        assert await queue.claim(s, "w") is not None
        await s.execute(text("UPDATE jobs SET locked_at = now() - interval '1 hour'"))
        assert await queue.heartbeat(s, job_id, "w") is True
        result = await queue.requeue_stale(s, 300)
        await s.commit()
    assert result == queue.StaleResult(requeued=0, failed=0)
    assert (await row(maker, job_id))["status"] == "running"


async def test_run_worker_end_to_end(maker: async_sessionmaker[AsyncSession]) -> None:
    ids = await enqueue_n(maker, 3)
    handled: list[int] = []

    async def handler(job: object) -> None:
        handled.append(job.id)  # type: ignore[attr-defined]

    count = await queue.run_worker({"k": handler}, "w", once=True, sessionmaker=maker)
    assert count == 3
    assert sorted(handled) == sorted(ids)
    statuses = [(await row(maker, i))["status"] for i in ids]
    assert statuses == ["done"] * len(ids)


async def _one(
    maker: async_sessionmaker[AsyncSession], max_attempts: int | None = None
) -> list[int]:
    return await enqueue_n(maker, 1, max_attempts=max_attempts)
