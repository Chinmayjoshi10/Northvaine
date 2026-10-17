"""brain/budget.py: the four-level money guard (DECISIONS D1-D5, D16).

Four caps are checked before every model call, in this order: per-call, per-run, per-day,
lifetime. A cap that would be exceeded raises `BudgetExceeded` and stops the call. The system
never silently degrades: no model downgrade, no truncated prompt, no partial result (D2).

Every attempt writes one `llm_calls` row - successes, transport failures, timeouts and
invalid-output retries alike (D4). Retries cost money, so they must be visible.

Two limitations you should know about before trusting a number here:

(a) **Check-then-call is not atomic.** Between `check_budget` and `record_call` nothing stops a
    second caller spending the same headroom. M2 therefore keeps model-call concurrency at one
    (D10); concurrency-safe reservations (a reserved-spend row, or an advisory lock) are parked
    in `docs/LATER.md`.

(b) **The lifetime cap is summed per database.** Spend recorded against `TEST_DATABASE_URL` and
    spend recorded against the production database are two independent "lifetimes" of the same
    wallet, and any call made outside `brain/llm.py` - a raw curl probe, say - writes no row and
    is invisible to both. The smoke script prints which database it summed from.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Protocol
from uuid import UUID, uuid4

from northvaine.brain.errors import BudgetExceeded
from northvaine.core.models import BudgetKind, LlmUsage
from northvaine.core.settings import ConfigError, get_settings

ERROR_MAX_CHARS = 2000


class Executor(Protocol):
    """The slice of an async SQLAlchemy session this module uses.

    Narrow on purpose: unit tests pass a fake, so they touch no database (T2.3).
    """

    async def execute(self, statement: Any, parameters: Any = None, /) -> Any: ...


@dataclass
class RunContext:
    """One logical run (a radar cycle, the smoke script, an onboarding session).

    Groups the calls of one run under one `run_id`, so the per-run cap (DECISIONS D1) and the
    `llm_calls` ledger can be attributed to it. `spent_usd` is the running total this process has
    recorded for this run; `check_budget` also re-sums the day and lifetime caps from the
    database, since those are shared across processes.
    """

    workspace_id: UUID | None = None
    run_id: UUID = field(default_factory=uuid4)
    spent_usd: Decimal = Decimal("0")
    # Calls of one run may run concurrently (the gate does); the budget check and the ledger
    # write share one database session, so they take turns under this lock.
    lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False, compare=False)

    @property
    def spent(self) -> Decimal:
        """What this run has recorded so far."""
        return self.spent_usd


DAY_SUM = (
    "SELECT COALESCE(SUM(cost_usd), 0) FROM llm_calls "
    "WHERE created_at >= :start AND created_at < :end "
    "AND workspace_id IS NOT DISTINCT FROM :workspace_id"
)
TOTAL_SUM = "SELECT COALESCE(SUM(cost_usd), 0) FROM llm_calls"

INSERT_CALL = (
    "INSERT INTO llm_calls ("
    "workspace_id, case_id, model, purpose, input_tokens, output_tokens, cost_usd, ok, "
    "run_id, prompt_version, latency_ms, error, provider"
    ") VALUES ("
    ":workspace_id, :case_id, :model, :purpose, :input_tokens, :output_tokens, :cost_usd, :ok, "
    ":run_id, :prompt_version, :latency_ms, :error, :provider"
    ")"
)


def utc_day_bounds(now: datetime | None = None) -> tuple[datetime, datetime]:
    """The half-open [start, end) of the current UTC day.

    Half-open is what makes the boundary unambiguous: 23:59:59Z belongs to one day and 00:00:00Z
    to the next, with no row counted twice and none missed.
    """
    moment = (now or datetime.now(UTC)).astimezone(UTC)
    start = moment.replace(hour=0, minute=0, second=0, microsecond=0)
    return start, start + timedelta(days=1)


async def _scalar(session: Executor, sql: str, params: dict[str, Any] | None = None) -> Decimal:
    from sqlalchemy import text

    result = await session.execute(text(sql), params or {})
    value = result.scalar_one()
    return Decimal(str(value if value is not None else 0))


async def check_budget(
    run: RunContext,
    estimated_cost: Decimal,
    *,
    session: Executor | None = None,
) -> None:
    """Raise `BudgetExceeded` if `estimated_cost` would breach any cap.

    Order is deliberate and tested: the cheapest check first, the one needing a database last.
    `MAX_CALL_COST_USD` (call), `RUN_BUDGET_USD` (run, from `run.spent_usd`), `DAILY_BUDGET_USD`
    (day, a per-workspace UTC-day sum; a NULL `workspace_id` is its own bucket - D3) and
    `TOTAL_BUDGET_USD` (total, summed across every row, globally).

    `DAILY_BUDGET_USD` and `TOTAL_BUDGET_USD` have no defaults: if either is unset this raises
    `ConfigError` naming the variable, so a missing cap can never read as an unlimited one.
    """
    settings = get_settings()

    if settings.daily_budget_usd is None:
        raise ConfigError(
            "DAILY_BUDGET_USD is not set. It has no default: set it in .env before any model "
            "call is made (DECISIONS D1)."
        )
    if settings.total_budget_usd is None:
        raise ConfigError(
            "TOTAL_BUDGET_USD is not set. It has no default: set it in .env before any model "
            "call is made (DECISIONS D1)."
        )

    if estimated_cost > settings.max_call_cost_usd:
        raise BudgetExceeded(
            BudgetKind.CALL, settings.max_call_cost_usd, Decimal("0"), estimated_cost
        )

    if run.spent_usd + estimated_cost > settings.run_budget_usd:
        raise BudgetExceeded(BudgetKind.RUN, settings.run_budget_usd, run.spent_usd, estimated_cost)

    if session is None:
        return  # the two shared caps need the ledger; callers without one get the local checks

    start, end = utc_day_bounds()
    spent_today = await _scalar(
        session, DAY_SUM, {"start": start, "end": end, "workspace_id": run.workspace_id}
    )
    if spent_today + estimated_cost > settings.daily_budget_usd:
        raise BudgetExceeded(BudgetKind.DAY, settings.daily_budget_usd, spent_today, estimated_cost)

    spent_ever = await _scalar(session, TOTAL_SUM)
    if spent_ever + estimated_cost > settings.total_budget_usd:
        raise BudgetExceeded(
            BudgetKind.TOTAL, settings.total_budget_usd, spent_ever, estimated_cost
        )


async def record_call(
    run: RunContext,
    *,
    session: Executor | None = None,
    model: str,
    purpose: str,
    usage: LlmUsage | None,
    cost_usd: Decimal,
    ok: bool,
    error: str | None,
    latency_ms: int,
    workspace_id: UUID | None = None,
    case_id: UUID | None = None,
    prompt_version: str | None = None,
    provider: str = "nebius",
) -> None:
    """Write one `llm_calls` row for this attempt.

    Every attempt is recorded - successes, transport failures, timeouts and invalid-JSON retries
    alike (D4). A failure with no reported `usage` records `cost_usd = 0` and `ok = False`, never
    an estimate: a guessed cost in an audit ledger is worse than a known-zero one.
    """
    recorded_cost = cost_usd if usage is not None else Decimal("0")
    if not ok and usage is None:
        recorded_cost = Decimal("0")

    run.spent_usd += recorded_cost

    if session is None:
        return

    from sqlalchemy import text

    await session.execute(
        text(INSERT_CALL),
        {
            "workspace_id": workspace_id if workspace_id is not None else run.workspace_id,
            "case_id": case_id,
            "model": model,
            "purpose": purpose,
            "input_tokens": usage.input_tokens if usage else None,
            "output_tokens": usage.output_tokens if usage else None,
            "cost_usd": recorded_cost,
            "ok": ok,
            "run_id": run.run_id,
            "prompt_version": prompt_version,
            "latency_ms": latency_ms,
            "error": error[:ERROR_MAX_CHARS] if error else None,
            "provider": provider,
        },
    )
