"""brain/budget.py: the four-level money guard (DECISIONS D1-D5, PLAN.md "Frozen contracts").

Every signature here is frozen for milestone 2. T2.3 fills in the bodies; nothing here makes a
network call or opens a database connection at import time.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from uuid import UUID, uuid4

from northvaine.core.models import LlmUsage


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


async def check_budget(run: RunContext, estimated_cost: Decimal, *, session: object = None) -> None:
    """Raise `BudgetExceeded` (brain/errors.py) if `estimated_cost` would breach any cap.

    Checks, in order: `MAX_CALL_COST_USD` (call), `RUN_BUDGET_USD` (run, from `run.spent_usd`),
    `DAILY_BUDGET_USD` (day, a per-workspace UTC-day sum of `llm_calls.cost_usd`; a NULL
    `workspace_id` is its own bucket — DECISIONS D3) and `TOTAL_BUDGET_USD` (total, summed across
    every row, globally). A cap that would be exceeded stops the call: no model downgrade, no
    truncated prompt, no partial result (DECISIONS D2). Check-then-call is not atomic; M2 keeps
    LLM call concurrency at one (DECISIONS D10).
    """
    raise NotImplementedError


async def record_call(
    run: RunContext,
    *,
    session: object = None,
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
) -> None:
    """Write one `llm_calls` row for this attempt.

    Every attempt is recorded — successes, transport failures, timeouts and invalid-JSON retries
    alike (DECISIONS D4). A failure with no reported `usage` records `cost_usd = 0` and
    `ok = False`, never an estimate. Updates `run.spent_usd` on success.
    """
    raise NotImplementedError
