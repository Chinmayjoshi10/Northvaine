"""Postgres-backed jobs queue (contract; implemented by T1.7).

Queue functions never commit: the caller owns the transaction. `run_worker` uses one
`session_scope()` for the claim and a separate one for the finish, so a claim is committed
before its handler runs. `heartbeat`, `complete` and `fail` only touch a row
`WHERE id = :id AND status = 'running' AND locked_by = :worker_id` and return False when no
row matched (the lease was lost). Handlers must be idempotent, and a long handler must call
`heartbeat` more often than `job_lease_seconds`.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING

from northvaine.core.models import Job, NewJob

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

Handler = Callable[[Job], Awaitable[None]]


@dataclass(frozen=True)
class StaleResult:
    """Counts from one `requeue_stale` pass."""

    requeued: int
    failed: int


async def enqueue(session: AsyncSession, job: NewJob) -> int:
    """Insert a queued job and return its id."""
    raise NotImplementedError("T1.7")


async def claim(
    session: AsyncSession, worker_id: str, kinds: Sequence[str] | None = None
) -> Job | None:
    """Lease the next ready job (SKIP LOCKED), or return None when nothing is ready."""
    raise NotImplementedError("T1.7")


async def heartbeat(session: AsyncSession, job_id: int, worker_id: str) -> bool:
    """Extend the lease on a running job this worker owns."""
    raise NotImplementedError("T1.7")


async def complete(session: AsyncSession, job_id: int, worker_id: str) -> bool:
    """Mark a running job this worker owns as done."""
    raise NotImplementedError("T1.7")


async def fail(session: AsyncSession, job_id: int, worker_id: str, error: str) -> bool:
    """Record an error; retry with backoff, or mark failed once attempts run out."""
    raise NotImplementedError("T1.7")


async def requeue_stale(session: AsyncSession, lease_seconds: int | None = None) -> StaleResult:
    """Return expired running jobs to queued, or to failed when attempts are used up."""
    raise NotImplementedError("T1.7")


def backoff_delay(
    attempts: int, *, base_seconds: float | None = None, max_seconds: float | None = None
) -> timedelta:
    """Capped exponential delay before the next attempt."""
    raise NotImplementedError("T1.7")


async def run_worker(
    handlers: Mapping[str, Handler],
    worker_id: str,
    *,
    once: bool = False,
    poll_seconds: float = 1.0,
    sessionmaker: async_sessionmaker[AsyncSession] | None = None,
) -> int:
    """Claim and run jobs whose kind has a handler; return the number processed."""
    raise NotImplementedError("T1.7")
