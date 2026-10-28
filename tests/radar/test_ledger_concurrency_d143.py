"""D143: the evidence ledger reads a few documents at once for the first radar only."""

from __future__ import annotations

import asyncio
from decimal import Decimal
from typing import Any

import httpx
import pytest

from northvaine.api.onboarding import QUICK_PROFILE
from northvaine.brain import llm
from northvaine.brain.errors import BudgetExceeded, LlmInvalidOutput
from northvaine.core.models import BudgetKind
from northvaine.core.settings import Settings
from northvaine.radar import run as run_module
from northvaine.radar.discover import RecordedPageFetcher
from northvaine.radar.run import run_radar, seeded_concepts
from northvaine.sensors.replay import replay_transport

from .test_run import AS_OF, SETTINGS, FakeLlm, RunContext, _env, recorded_world  # noqa: F401

REAL = run_module.build_evidence


async def _fake_result(doc: Any, *a: Any, **k: Any) -> Any:
    return await REAL(doc, *a, **k)  # the scripted model answers; only the timing is faked


async def _ledger(
    monkeypatch: pytest.MonkeyPatch, concurrency: int, fake_build: Any
) -> tuple[list[Any], Any]:
    monkeypatch.setattr(run_module, "build_evidence", fake_build)
    spec, exchanges, pages = recorded_world("stone_supplier")
    out: list[Any] = []
    settings = SETTINGS.model_copy(update={"radar_ledger_concurrency": concurrency})
    async with httpx.AsyncClient(transport=replay_transport(exchanges, match_body=False)) as http:
        with llm.client_override(FakeLlm()):
            result = await run_radar(
                spec,
                as_of=AS_OF,
                http=http,
                fetcher=RecordedPageFetcher(pages),
                concepts=seeded_concepts(),
                run=RunContext(),
                settings=settings,
                evidence_out=out,
            )
    return out, result


async def test_four_at_once_gives_the_same_results_order_as_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def build(doc: Any, *a: Any, **k: Any) -> Any:
        await asyncio.sleep(0.001 * (len(doc.url) % 5))  # finish out of order
        return await _fake_result(doc, *a, **k)

    one, r1 = await _ledger(monkeypatch, 1, build)
    four, r4 = await _ledger(monkeypatch, 4, build)
    assert len(one) > 4
    assert [d.url for d, _ in one] == [d.url for d, _ in four]
    assert [x.eligibility.kind.value for _, x in one] == [x.eligibility.kind.value for _, x in four]
    assert r1.llm_calls == r4.llm_calls


async def test_at_most_four_run_at_once(monkeypatch: pytest.MonkeyPatch) -> None:
    live = peak = 0

    async def build(doc: Any, *a: Any, **k: Any) -> Any:
        nonlocal live, peak
        live += 1
        peak = max(peak, live)
        await asyncio.sleep(0.005)
        live -= 1
        return await _fake_result(doc, *a, **k)

    await _ledger(monkeypatch, 4, build)
    assert peak == 4


async def test_a_failing_document_is_noted_and_skipped(monkeypatch: pytest.MonkeyPatch) -> None:
    bad: list[str] = []

    async def build(doc: Any, *a: Any, **k: Any) -> Any:
        if not bad:
            bad.append(doc.url)
            raise LlmInvalidOutput("truncated output")
        return await _fake_result(doc, *a, **k)

    out, result = await _ledger(monkeypatch, 4, build)
    assert f"document skipped (LlmInvalidOutput): {bad[0]}" in result.notes
    assert bad[0] not in [d.url for d, _ in out]
    assert out


async def test_budget_exceeded_stops_new_documents(monkeypatch: pytest.MonkeyPatch) -> None:
    started = 0

    async def build(doc: Any, *a: Any, **k: Any) -> Any:
        nonlocal started
        started += 1
        if started == 3:
            raise BudgetExceeded(BudgetKind.RUN, Decimal(1), Decimal(1), Decimal(2))
        await asyncio.sleep(0.005)
        return await _fake_result(doc, *a, **k)

    out, result = await _ledger(monkeypatch, 4, build)
    assert any(n.startswith("stopped reading documents") for n in result.notes)
    assert started < 12 and len(out) < started


def test_only_the_first_radar_reads_documents_in_parallel() -> None:
    assert Settings(_env_file=None).radar_ledger_concurrency == 1
    assert QUICK_PROFILE["radar_ledger_concurrency"] == 4
