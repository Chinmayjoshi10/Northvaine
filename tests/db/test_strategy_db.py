"""Learning loop v0, database side (D89). Marked `db`: a recorded run is saved, a simulated owner
rates its cases, and `learn` writes a strategy version from those labels only."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from northvaine.core import db
from northvaine.radar.persist import persist_run
from northvaine.radar.strategy import learn, load_strategy
from tests.radar.test_radar_replay import load, radar, spec_of

pytestmark = pytest.mark.db

CLIENT = "packaging_supplier"


@pytest.fixture(scope="module")
def run_and_evidence() -> tuple[Any, list[Any]]:
    evidence: list[Any] = []
    run = asyncio.run(radar.run_replay(spec_of(CLIENT), load(CLIENT), evidence_out=evidence))
    return run, evidence


@pytest_asyncio.fixture
async def maker(migrated_url: str) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine: AsyncEngine = db.create_engine(migrated_url)
    try:
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()


async def _rate(s: AsyncSession, case_ids: list[Any], rating: str, source: str) -> None:
    for case_id in case_ids:
        await s.execute(
            text("INSERT INTO feedback (case_id, rating, source) VALUES (:c, :r, :s)"),
            {"c": case_id, "r": rating, "s": source},
        )


async def test_learning_uses_only_the_labels_it_is_allowed_and_versions_them(
    maker: async_sessionmaker[AsyncSession], run_and_evidence: tuple[Any, list[Any]]
) -> None:
    run, evidence = run_and_evidence
    async with maker() as s:
        saved = await persist_run(s, run, evidence, workspace_name="SIMULATED owner study")
        cases = list(saved.cases.values())
        half = len(cases) // 2
        await _rate(s, cases[:half], "good", "simulated")
        await _rate(s, cases[half:], "not_relevant", "simulated")
        await s.commit()

        assert await load_strategy(s, saved.workspace_id) is None
        # an owner's learning never reads simulated labels (D79)
        owner = await learn(s, saved.workspace_id)
        assert owner.labels == 0
        sim = await learn(s, saved.workspace_id, simulated=True)
        await s.commit()
        assert sim.version == owner.version + 1
        assert sim.labels == len(cases)

        strategy = await load_strategy(s, saved.workspace_id)
        assert strategy is not None and strategy.version == sim.version
        assert strategy.yields["source"] and strategy.yields["query"]
        assert 0 < strategy.posteriors().pooled.mean < 1
        # earlier versions stay: rollback is loading an earlier version
        first = await load_strategy(s, saved.workspace_id, version=owner.version)
        assert first is not None and first.version == owner.version
        rows = await s.execute(
            text(
                "SELECT count(*) FROM beliefs WHERE workspace_id = :w AND strategy_version = :v "
                "AND prior_source = 'simulated'"
            ),
            {"w": saved.workspace_id, "v": sim.version},
        )
        assert rows.scalar_one() > 0
        changes = await s.execute(
            text("SELECT changes FROM strategy_versions WHERE workspace_id = :w AND version = :v"),
            {"w": saved.workspace_id, "v": sim.version},
        )
        assert changes.scalar_one()


async def test_owner_feedback_records_become_labels_once(
    maker: async_sessionmaker[AsyncSession], run_and_evidence: tuple[Any, list[Any]]
) -> None:
    from northvaine.radar.labels import cases_for_run, import_feedback

    run, evidence = run_and_evidence
    ranks = [e.rank for e in run.entries]
    records = [
        {"rank": ranks[0], "relevant": True, "actionable": True,
         "received_at": "2026-10-09T10:00:00+00:00"},
        {"rank": ranks[1], "failure_chip": "not a buyer",
         "received_at": "2026-10-09T10:01:00+00:00"},
        {"rank": ranks[2], "known_already": True,  # teaches nothing yet
         "received_at": "2026-10-09T10:02:00+00:00"},
        {"rank": 9999, "relevant": True, "actionable": True,  # no such entry
         "received_at": "2026-10-09T10:03:00+00:00"},
    ]  # fmt: skip
    async with maker() as s:
        saved = await persist_run(s, run, evidence)
        cases = await cases_for_run(s, saved.workspace_id, run)
        assert set(cases) == set(ranks)
        assert cases[ranks[0]] == saved.cases[run.entries[0].candidate.key]
        assert await import_feedback(s, records, cases) == 2
        assert await import_feedback(s, records, cases) == 0  # idempotent
        await s.commit()
        owner = await learn(s, saved.workspace_id)
        await s.commit()
    assert owner.labels == 2
