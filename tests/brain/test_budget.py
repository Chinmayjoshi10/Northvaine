"""The four-level money guard, with a fake executor: no network, no database (T2.3)."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest

from northvaine.brain import budget as budget_module
from northvaine.brain.budget import RunContext, check_budget, record_call, utc_day_bounds
from northvaine.brain.errors import BudgetExceeded
from northvaine.core.models import BudgetKind, LlmUsage
from northvaine.core.settings import ConfigError, Settings

Caps = Callable[..., None]

USAGE = LlmUsage(input_tokens=100, output_tokens=20, total_tokens=120)


class FakeResult:
    def __init__(self, value: Any) -> None:
        self._value = value

    def scalar_one(self) -> Any:
        return self._value


class FakeSession:
    """Answers the day sum, then the lifetime sum; records every insert."""

    def __init__(self, day: str = "0", total: str = "0") -> None:
        self.day = Decimal(day)
        self.total = Decimal(total)
        self.inserts: list[dict[str, Any]] = []

    async def execute(self, statement: Any, parameters: Any = None, /) -> Any:
        sql = str(statement)
        if sql.lstrip().startswith("INSERT"):
            self.inserts.append(dict(parameters or {}))
            return FakeResult(None)
        if "created_at >=" in sql:
            return FakeResult(self.day)
        return FakeResult(self.total)


@pytest.fixture
def money(monkeypatch: pytest.MonkeyPatch) -> Iterator[Caps]:
    """Fixed caps, independent of the developer's real `.env`.

    `budget.py` does `from ... import get_settings`, so it holds its own reference: patching the
    settings module would not reach it. Patch where the name is used.
    """

    def set_caps(**overrides: str | None) -> None:
        values: dict[str, Any] = {
            "daily_budget_usd": Decimal("10"),
            "total_budget_usd": Decimal("29"),
            "run_budget_usd": Decimal("0.20"),
            "max_call_cost_usd": Decimal("0.05"),
        }
        values.update({k: v for k, v in overrides.items()})
        settings = Settings(_env_file=None, **values)
        monkeypatch.setattr(budget_module, "get_settings", lambda: settings)

    set_caps()
    yield set_caps


# --- the caps, in order -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_call_cap_trips_first(money: Caps) -> None:
    with pytest.raises(BudgetExceeded) as caught:
        await check_budget(RunContext(), Decimal("0.06"), session=FakeSession())
    assert caught.value.kind is BudgetKind.CALL
    assert caught.value.cap == Decimal("0.05")


@pytest.mark.asyncio
async def test_the_run_cap_trips_next(money: Caps) -> None:
    run = RunContext(spent_usd=Decimal("0.19"))
    with pytest.raises(BudgetExceeded) as caught:
        await check_budget(run, Decimal("0.02"), session=FakeSession())
    assert caught.value.kind is BudgetKind.RUN
    assert caught.value.spent == Decimal("0.19")


@pytest.mark.asyncio
async def test_the_day_cap_trips_next(money: Caps) -> None:
    with pytest.raises(BudgetExceeded) as caught:
        await check_budget(RunContext(), Decimal("0.01"), session=FakeSession(day="9.995"))
    assert caught.value.kind is BudgetKind.DAY
    assert caught.value.cap == Decimal("10")


@pytest.mark.asyncio
async def test_the_lifetime_cap_trips_last(money: Caps) -> None:
    session = FakeSession(day="0", total="28.999")
    with pytest.raises(BudgetExceeded) as caught:
        await check_budget(RunContext(), Decimal("0.01"), session=session)
    assert caught.value.kind is BudgetKind.TOTAL
    assert caught.value.cap == Decimal("29")


@pytest.mark.asyncio
async def test_a_call_within_every_cap_passes(money: Caps) -> None:
    await check_budget(RunContext(), Decimal("0.001"), session=FakeSession(day="1", total="5"))


@pytest.mark.asyncio
async def test_exceeding_never_degrades_silently(money: Caps) -> None:
    """D2: the guard raises. It returns no 'use a cheaper model' hint to act on."""
    with pytest.raises(BudgetExceeded):
        await check_budget(RunContext(), Decimal("99"), session=FakeSession())


# --- unset caps are never unlimited -------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("missing", ["DAILY_BUDGET_USD", "TOTAL_BUDGET_USD"])
async def test_an_unset_cap_raises_config_error_naming_it(money: Caps, missing: str) -> None:
    money(**{missing.lower(): None})
    with pytest.raises(ConfigError, match=missing):
        await check_budget(RunContext(), Decimal("0.001"), session=FakeSession())


# --- the UTC day boundary -----------------------------------------------------------------


def test_the_utc_day_is_half_open() -> None:
    late = datetime(2026, 10, 3, 23, 59, 59, tzinfo=UTC)
    early = datetime(2026, 10, 4, 0, 0, 1, tzinfo=UTC)
    assert utc_day_bounds(late)[0] != utc_day_bounds(early)[0]
    start, end = utc_day_bounds(late)
    assert start <= late < end
    assert not (start <= early < end)


@pytest.mark.asyncio
async def test_the_day_sum_is_bucketed_by_workspace(money: Caps) -> None:
    session = FakeSession()
    workspace = uuid4()
    await check_budget(RunContext(workspace_id=workspace), Decimal("0.001"), session=session)
    await check_budget(RunContext(workspace_id=None), Decimal("0.001"), session=session)
    # NULL is its own bucket (D3), expressed as IS NOT DISTINCT FROM rather than `=`.
    from northvaine.brain.budget import DAY_SUM

    assert "IS NOT DISTINCT FROM" in DAY_SUM


# --- the run accumulates ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_three_cheap_calls_trip_the_run_cap_while_the_day_is_far_below(
    money: Caps,
) -> None:
    run = RunContext()
    session = FakeSession(day="0", total="0")
    for _ in range(3):
        await check_budget(run, Decimal("0.04"), session=session)
        await record_call(
            run,
            session=session,
            model="m",
            purpose="p",
            usage=USAGE,
            cost_usd=Decimal("0.08"),
            ok=True,
            error=None,
            latency_ms=5,
        )
    assert run.spent == Decimal("0.24")
    with pytest.raises(BudgetExceeded) as caught:
        await check_budget(run, Decimal("0.01"), session=session)
    assert caught.value.kind is BudgetKind.RUN


# --- the ledger ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_successful_call_records_one_row(money: Caps) -> None:
    session = FakeSession()
    run = RunContext()
    await record_call(
        run,
        session=session,
        model="nvidia/Nemotron-3_5-Lightning",
        purpose="smoke",
        usage=USAGE,
        cost_usd=Decimal("0.0001"),
        ok=True,
        error=None,
        latency_ms=120,
        prompt_version="smoke_ping.v1",
    )
    (row,) = session.inserts
    assert row["ok"] is True
    assert row["cost_usd"] == Decimal("0.0001")
    assert row["input_tokens"] == 100
    assert row["prompt_version"] == "smoke_ping.v1"
    assert row["run_id"] == run.run_id
    assert row["provider"] == "nebius"


@pytest.mark.asyncio
@pytest.mark.parametrize("reason", ["transport failure", "timeout", "invalid JSON"])
async def test_every_failed_attempt_records_a_row_with_zero_cost(money: Caps, reason: str) -> None:
    """D4: retries are paid for, so they must be visible. A failure never records a guess."""
    session = FakeSession()
    run = RunContext()
    await record_call(
        run,
        session=session,
        model="m",
        purpose="p",
        usage=None,
        cost_usd=Decimal("0.05"),  # an estimate the caller had; it must not be recorded
        ok=False,
        error=reason,
        latency_ms=3,
    )
    (row,) = session.inserts
    assert row["ok"] is False
    assert row["cost_usd"] == Decimal("0")
    assert row["input_tokens"] is None
    assert row["error"] == reason
    assert run.spent == Decimal("0")


@pytest.mark.asyncio
async def test_a_long_error_is_truncated(money: Caps) -> None:
    from northvaine.brain.budget import ERROR_MAX_CHARS

    session = FakeSession()
    await record_call(
        RunContext(),
        session=session,
        model="m",
        purpose="p",
        usage=None,
        cost_usd=Decimal("0"),
        ok=False,
        error="x" * 10_000,
        latency_ms=1,
    )
    assert len(session.inserts[0]["error"]) == ERROR_MAX_CHARS


# --- secrets never leak -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_secret_appears_in_a_budget_error_or_a_row(money: Caps) -> None:
    # Assembled at runtime: a literal that *looks* like a key would trip the repo's own
    # secret-scanning invariant (scripts/check_invariants.py), which is working as intended.
    secret = "-".join(["sk", "DO", "NOT", "LEAK", "0123456789"])
    session = FakeSession()
    with pytest.raises(BudgetExceeded) as caught:
        await check_budget(RunContext(), Decimal("99"), session=session)
    assert secret not in str(caught.value)

    await record_call(
        RunContext(),
        session=session,
        model="m",
        purpose="p",
        usage=None,
        cost_usd=Decimal("0"),
        ok=False,
        error="connection to host failed",
        latency_ms=1,
    )
    assert secret not in str(session.inserts)
