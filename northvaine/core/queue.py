"""Postgres-backed jobs queue (contract frozen in T1.0; implemented by T1.7).

Queue functions never commit: the caller owns the transaction. `run_worker` uses one
`session_scope()` for the claim and a separate one for the finish, so a claim is committed
before its handler runs. `heartbeat`, `complete` and `fail` only touch a row
`WHERE id = :id AND status = 'running' AND locked_by = :worker_id` and return False when no
row matched (the lease was lost). Handlers must be idempotent, and a long handler must call
`heartbeat` more often than `job_lease_seconds`.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from northvaine.core import settings as settings_module
from northvaine.core.models import Job, NewJob

if TYPE_CHECKING:
    from sqlalchemy import TableClause
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

logger = logging.getLogger(__name__)

Handler = Callable[[Job], Awaitable[None]]

ERROR_MAX_CHARS = 2000
_COLUMNS = (
    "id",
    "kind",
    "payload",
    "status",
    "attempts",
    "max_attempts",
    "run_after",
    "locked_at",
    "locked_by",
    "error",
    "workspace_id",
    "created_at",
    "finished_at",
)


@dataclass(frozen=True)
class StaleResult:
    """Counts from one `requeue_stale` pass."""

    requeued: int
    failed: int


def _jobs() -> TableClause:
    """A light `jobs` table description (no metadata; SQLAlchemy is imported on demand)."""
    import sqlalchemy as sa
    from sqlalchemy.dialects.postgresql import JSONB

    return sa.table(
        "jobs",
        sa.column("id", sa.BigInteger),
        sa.column("kind", sa.Text),
        sa.column("payload", JSONB),
        sa.column("status", sa.Text),
        sa.column("attempts", sa.Integer),
        sa.column("max_attempts", sa.Integer),
        sa.column("run_after", sa.DateTime(timezone=True)),
        sa.column("locked_at", sa.DateTime(timezone=True)),
        sa.column("locked_by", sa.Text),
        sa.column("error", sa.Text),
        sa.column("workspace_id", sa.Uuid),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("finished_at", sa.DateTime(timezone=True)),
    )


def _claim_statement(worker_id: str, kinds: Sequence[str] | None = None) -> Any:
    """The single-statement claim: UPDATE ... WHERE id = (SELECT ... FOR UPDATE SKIP LOCKED)."""
    import sqlalchemy as sa

    jobs = _jobs()
    ready = [jobs.c.status == "queued", jobs.c.run_after <= sa.func.now()]
    if kinds is not None:
        ready.append(jobs.c.kind == sa.any_(sa.literal(list(kinds), sa.ARRAY(sa.Text))))
    picked = (
        sa.select(jobs.c.id)
        .where(*ready)
        .order_by(jobs.c.run_after, jobs.c.id)
        .limit(1)
        .with_for_update(skip_locked=True)
        .scalar_subquery()
    )
    return (
        sa.update(jobs)
        .where(jobs.c.id == picked)
        .values(
            status="running",
            attempts=jobs.c.attempts + 1,
            locked_at=sa.func.now(),
            locked_by=worker_id,
        )
        .returning(*[jobs.c[name] for name in _COLUMNS])
    )


def _owned(jobs: TableClause, job_id: int, worker_id: str) -> list[Any]:
    return [jobs.c.id == job_id, jobs.c.status == "running", jobs.c.locked_by == worker_id]


def backoff_delay(
    attempts: int, *, base_seconds: float | None = None, max_seconds: float | None = None
) -> timedelta:
    """Capped exponential delay before the next attempt: min(max, base * 2**(attempts-1))."""
    settings = settings_module.get_settings()
    base = settings.job_backoff_base_seconds if base_seconds is None else base_seconds
    cap = settings.job_backoff_max_seconds if max_seconds is None else max_seconds
    exponent = max(attempts - 1, 0)
    if exponent > 64:  # the cap always wins; avoid building a huge number
        return timedelta(seconds=cap)
    return timedelta(seconds=min(cap, base * 2**exponent))


def _clean_error(error: str) -> str:
    """Replace known secret values with *** and cut to ERROR_MAX_CHARS."""
    from pydantic import SecretStr

    settings = settings_module.get_settings()
    secrets: list[str] = []
    for name in type(settings).model_fields:
        value = getattr(settings, name, None)
        if isinstance(value, SecretStr) and value.get_secret_value():
            secrets.append(value.get_secret_value())
    for secret in sorted(secrets, key=len, reverse=True):
        error = error.replace(secret, "***")
    return error[:ERROR_MAX_CHARS]


async def enqueue(session: AsyncSession, job: NewJob) -> int:
    """Insert a queued job and return its id."""
    import sqlalchemy as sa

    jobs = _jobs()
    values: dict[str, Any] = {
        "kind": job.kind,
        "payload": job.payload,
        "max_attempts": job.max_attempts or settings_module.get_settings().job_max_attempts,
        "workspace_id": job.workspace_id,
    }
    if job.run_after is not None:
        values["run_after"] = job.run_after
    result = await session.execute(sa.insert(jobs).values(**values).returning(jobs.c.id))
    return int(result.scalar_one())


async def claim(
    session: AsyncSession, worker_id: str, kinds: Sequence[str] | None = None
) -> Job | None:
    """Lease the next ready job (SKIP LOCKED), or return None when nothing is ready."""
    result = await session.execute(_claim_statement(worker_id, kinds))
    row = result.mappings().first()
    return Job.model_validate(dict(row)) if row is not None else None


async def heartbeat(session: AsyncSession, job_id: int, worker_id: str) -> bool:
    """Extend the lease on a running job this worker owns."""
    import sqlalchemy as sa

    jobs = _jobs()
    stmt = (
        sa.update(jobs)
        .where(*_owned(jobs, job_id, worker_id))
        .values(locked_at=sa.func.now())
        .returning(jobs.c.id)
    )
    return (await session.execute(stmt)).first() is not None


async def complete(session: AsyncSession, job_id: int, worker_id: str) -> bool:
    """Mark a running job this worker owns as done."""
    import sqlalchemy as sa

    jobs = _jobs()
    stmt = (
        sa.update(jobs)
        .where(*_owned(jobs, job_id, worker_id))
        .values(status="done", finished_at=sa.func.now())
        .returning(jobs.c.id)
    )
    return (await session.execute(stmt)).first() is not None


async def fail(session: AsyncSession, job_id: int, worker_id: str, error: str) -> bool:
    """Record an error; retry with backoff, or mark failed once attempts run out."""
    import sqlalchemy as sa

    jobs = _jobs()
    owned = _owned(jobs, job_id, worker_id)
    row = (
        await session.execute(
            sa.select(jobs.c.attempts, jobs.c.max_attempts).where(*owned).with_for_update()
        )
    ).first()
    if row is None:
        return False
    attempts, max_attempts = int(row[0]), int(row[1])
    message = _clean_error(error)
    if attempts < max_attempts:
        values: dict[str, Any] = {
            "status": "queued",
            "run_after": sa.func.now() + backoff_delay(attempts),
            "locked_at": None,
            "locked_by": None,
            "error": message,
        }
    else:
        values = {"status": "failed", "finished_at": sa.func.now(), "error": message}
    result = await session.execute(
        sa.update(jobs).where(*owned).values(**values).returning(jobs.c.id)
    )
    return result.first() is not None


async def requeue_stale(session: AsyncSession, lease_seconds: int | None = None) -> StaleResult:
    """Return expired running jobs to queued, or to failed when attempts are used up."""
    import sqlalchemy as sa

    if lease_seconds is None:
        lease_seconds = settings_module.get_settings().job_lease_seconds
    jobs = _jobs()
    expired = [
        jobs.c.status == "running",
        jobs.c.locked_at < sa.func.now() - timedelta(seconds=lease_seconds),
    ]
    failed = await session.execute(
        sa.update(jobs)
        .where(*expired, jobs.c.attempts >= jobs.c.max_attempts)
        .values(status="failed", finished_at=sa.func.now(), error="lease expired")
        .returning(jobs.c.id)
    )
    requeued = await session.execute(
        sa.update(jobs)
        .where(*expired, jobs.c.attempts < jobs.c.max_attempts)
        .values(status="queued", locked_at=None, locked_by=None)
        .returning(jobs.c.id)
    )
    return StaleResult(requeued=len(requeued.all()), failed=len(failed.all()))


@asynccontextmanager
async def _scope(sessionmaker: async_sessionmaker[AsyncSession] | None) -> AsyncIterator[Any]:
    """One transaction: commit on success, roll back on error."""
    if sessionmaker is None:
        from northvaine.core.db import session_scope

        async with session_scope() as session:
            yield session
        return
    async with sessionmaker() as session:
        try:
            yield session
            await session.commit()
        except BaseException:
            await session.rollback()
            raise


async def _run_one(
    handlers: Mapping[str, Handler],
    worker_id: str,
    sessionmaker: async_sessionmaker[AsyncSession] | None,
) -> bool:
    """Claim and process one job. Return False when nothing was ready."""
    async with _scope(sessionmaker) as session:
        job = await claim(session, worker_id)
    if job is None:
        return False

    error: str | None = None
    handler = handlers.get(job.kind)
    if handler is None:
        error = f"no handler for kind '{job.kind}'"
    else:
        try:
            await handler(job)
        except Exception as exc:
            logger.warning("job %s (%s) failed: %s", job.id, job.kind, type(exc).__name__)
            error = str(exc) or type(exc).__name__

    async with _scope(sessionmaker) as session:
        if error is None:
            matched = await complete(session, job.id, worker_id)
        else:
            matched = await fail(session, job.id, worker_id, error)
    if not matched:
        logger.warning("job %s: lease lost before it could be finished", job.id)
    return True


async def run_worker(
    handlers: Mapping[str, Handler],
    worker_id: str,
    *,
    once: bool = False,
    poll_seconds: float = 1.0,
    sessionmaker: async_sessionmaker[AsyncSession] | None = None,
) -> int:
    """Claim and run jobs whose kind has a handler; return the number processed.

    With `once=True` it drains the jobs that are ready now and returns. Otherwise it polls
    forever, recovering stale leases whenever it is idle.
    """
    processed = 0
    while True:
        if await _run_one(handlers, worker_id, sessionmaker):
            processed += 1
            continue
        if once:
            return processed
        async with _scope(sessionmaker) as session:
            await requeue_stale(session)
        await asyncio.sleep(poll_seconds)
