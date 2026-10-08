"""Saving a radar run (D86). Marked `db`: a recorded run, replayed offline, saved into a real
database twice. The second save must update the same cases, never duplicate them."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from northvaine.core import db
from northvaine.radar.models import RejectedAs
from northvaine.radar.persist import persist_run
from tests.radar.test_radar_replay import load, radar, spec_of

pytestmark = pytest.mark.db

CLIENT = "packaging_supplier"  # the smallest recording


@pytest_asyncio.fixture
async def maker(migrated_url: str) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine: AsyncEngine = db.create_engine(migrated_url)
    try:
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()


async def scalar(s: AsyncSession, sql: str, **params: Any) -> Any:
    return (await s.execute(text(sql), params)).scalar_one()


@pytest.fixture(scope="module")
def run_and_evidence() -> tuple[Any, list[Any]]:
    # Replayed outside the test's event loop: run_replay drives its own loop.
    evidence: list[Any] = []
    run = asyncio.run(radar.run_replay(spec_of(CLIENT), load(CLIENT), evidence_out=evidence))
    return run, evidence


async def test_a_run_is_saved_once_and_a_second_save_updates_it(
    maker: async_sessionmaker[AsyncSession], run_and_evidence: tuple[Any, list[Any]]
) -> None:
    run, evidence = run_and_evidence
    assert run.entries and evidence

    async with maker() as s:
        first = await persist_run(s, run, evidence)
        await s.commit()
    async with maker() as s:
        second = await persist_run(s, run, evidence)
        await s.commit()

    assert first.workspace_id == second.workspace_id
    assert set(first.cases) == {e.candidate.key for e in run.entries}
    assert first.cases == second.cases  # same case rows, updated
    assert first.documents_inserted > 0 and second.documents_inserted == 0

    async with maker() as s:
        assert await scalar(s, "SELECT count(*) FROM workspaces") == 1
        assert await scalar(s, "SELECT count(*) FROM cases") == len(run.entries)
        assert await scalar(s, "SELECT count(DISTINCT stage) FROM cases") == 1
        assert await scalar(s, "SELECT min(jsonb_array_length(trace)) FROM cases") == 2
        gated = len(run.entries) + len(run.rejected)
        assert await scalar(s, "SELECT count(*) FROM decisions") == 2 * gated
        # case evidence is verified claims only (CLAUDE.md #2)
        assert (
            await scalar(
                s,
                "SELECT count(*) FROM case_evidence e JOIN claims c ON c.id = e.claim_id "
                "WHERE NOT c.verified",
            )
            == 0
        )
        assert await scalar(s, "SELECT count(*) FROM case_evidence") == sum(
            len({c.fingerprint for c in e.candidate.claims}) for e in run.entries
        )
        questions = sum(len(set(e.skeptic.open_questions)) for e in run.entries)
        assert await scalar(s, "SELECT count(*) FROM case_open_questions") == questions


async def test_no_company_row_for_an_unidentified_subject(
    maker: async_sessionmaker[AsyncSession], run_and_evidence: tuple[Any, list[Any]]
) -> None:
    run, evidence = run_and_evidence
    hidden = {
        r.candidate.key
        for r in run.rejected
        if r.gate.rejected_as in {RejectedAs.UNIDENTIFIED, RejectedAs.NOT_AN_ORGANISATION}
    }
    async with maker() as s:
        await persist_run(s, run, evidence)
        await s.commit()
    async with maker() as s:
        keys = set(
            (await s.execute(text("SELECT attributes->>'radar_key' FROM companies"))).scalars()
        )
        reasons = list(
            (
                await s.execute(
                    text("SELECT choice->>'reason' FROM decisions WHERE company_id IS NULL")
                )
            ).scalars()
        )
    assert not (keys & hidden)
    assert all(reason is None for reason in reasons)


async def test_a_case_moved_past_briefed_is_never_moved_back(
    maker: async_sessionmaker[AsyncSession], run_and_evidence: tuple[Any, list[Any]]
) -> None:
    run, evidence = run_and_evidence
    async with maker() as s:
        saved = await persist_run(s, run, evidence)
        case_id = next(iter(saved.cases.values()))
        await s.execute(
            text("UPDATE cases SET stage = 'contacted' WHERE id = :id"), {"id": case_id}
        )
        await s.commit()
    async with maker() as s:
        again = await persist_run(s, run, evidence)
        await s.commit()
        assert case_id in again.cases.values()
        assert await scalar(s, "SELECT stage FROM cases WHERE id = :id", id=case_id) == (
            "contacted"
        )
