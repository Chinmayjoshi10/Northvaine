"""Live ledger store checks (T4.4). Marked `db`."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from northvaine.core import db, ledger
from northvaine.core.models import (
    ClaimCheck,
    ClaimDraft,
    ClaimStatus,
    ConceptAssignment,
    NewEvent,
    SubjectMention,
)

pytestmark = pytest.mark.db

T0 = datetime(2026, 3, 1, tzinfo=UTC)


@pytest_asyncio.fixture
async def maker(migrated_url: str) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine: AsyncEngine = db.create_engine(migrated_url)
    try:
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()


async def add_doc(
    s: AsyncSession, url: str, available_at: datetime | None, workspace_id: UUID | None = None
) -> UUID:
    row = await s.execute(
        text(
            "INSERT INTO documents (url, content_hash, text, available_at, workspace_id) "
            "VALUES (:u, :u, 'body', :a, :w) RETURNING id"
        ),
        {"u": url, "a": available_at, "w": workspace_id},
    )
    return row.scalar_one()


def mk(doc_id: UUID, fp: str, status: ClaimStatus = ClaimStatus.VERIFIED) -> ClaimCheck:
    ok = status == ClaimStatus.VERIFIED
    return ClaimCheck(
        document_id=doc_id,
        draft=ClaimDraft(
            statement=f"s-{fp}",
            source_quote="body",
            subject=SubjectMention(name="Acme", country="DE", role="buyer"),
            extracted_by="m",
        ),
        status=status,
        quote_offset=0 if ok else None,
        verified_by="code" if ok else None,
        fingerprint=fp,
    )


async def count(s: AsyncSession, table: str) -> int:
    return (await s.execute(text(f"SELECT count(*) FROM {table}"))).scalar_one()


async def test_save_claims_is_idempotent_and_stores_meta(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    async with maker() as s:
        d = await add_doc(s, "u1", T0)
        checks = [mk(d, "a"), mk(d, "b", ClaimStatus.QUOTE_NOT_FOUND)]
        first = await ledger.save_claims(s, checks)
        again = await ledger.save_claims(s, checks)
        assert set(first) == {"a", "b"} and first == again
        assert await count(s, "claims") == 2
        row = (
            (await s.execute(text("SELECT * FROM claims WHERE fingerprint = 'b'"))).mappings().one()
        )
        assert row["status"] == "quote_not_found" and row["verified"] is False
        assert row["meta"]["subject"]["name"] == "Acme"


async def test_verified_claims_scope_and_time(maker: async_sessionmaker[AsyncSession]) -> None:
    async with maker() as s:
        ws_a = (
            await s.execute(text("INSERT INTO workspaces (name) VALUES ('a') RETURNING id"))
        ).scalar_one()
        ws_b = (
            await s.execute(text("INSERT INTO workspaces (name) VALUES ('b') RETURNING id"))
        ).scalar_one()
        pub = await add_doc(s, "pub", T0)
        future = await add_doc(s, "future", T0 + timedelta(days=5))
        undated = await add_doc(s, "undated", None)
        priv_a = await add_doc(s, "pa", T0, ws_a)
        priv_b = await add_doc(s, "pb", T0, ws_b)
        await ledger.save_claims(
            s,
            [
                mk(pub, "ok"),
                mk(pub, "bad", ClaimStatus.QUOTE_NOT_FOUND),
                mk(future, "fut"),
                mk(undated, "und"),
                mk(priv_a, "pa"),
                mk(priv_b, "pb"),
            ],
        )
        public = {c.document_id for c in await ledger.verified_claims(s)}
        assert public == {pub, future, undated}
        as_of = {c.document_id for c in await ledger.verified_claims(s, as_of=T0)}
        assert as_of == {pub}
        scoped = await ledger.verified_claims(s, as_of=T0, workspace_id=ws_a)
        assert {c.document_id for c in scoped} == {pub, priv_a}
        only = await ledger.verified_claims(s, document_ids=[pub])
        assert [c.statement for c in only] == ["s-ok"]


async def test_checks_reject_incomplete_verified_rows(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    async with maker() as s:
        d = await add_doc(s, "u", T0)
        await s.commit()
    insert = (
        "INSERT INTO claims (document_id, statement, source_quote, quote_offset, verified, "
        "verified_by, extracted_by, status, fingerprint) "
        "VALUES (:d, 's', 'q', :off, true, 'code', 'm', :status, :fp)"
    )
    for off, status, fp in [(None, "verified", "x1"), (1, "unsupported", "x2")]:
        async with maker() as s:
            with pytest.raises(IntegrityError):
                await s.execute(text(insert), {"d": d, "off": off, "status": status, "fp": fp})


def new_event(claim_ids: list[UUID], fp: str, **kw: object) -> NewEvent:
    base: dict[str, object] = {
        "event_type": "facility_opened",
        "claim_ids": claim_ids,
        "occurred_on": date(2026, 2, 1),
        "available_at": T0,
        "description": "desc",
        "embedding": [0.1] * 1024,
        "cluster_id": uuid4(),
        "slots": {"city": "X"},
        "details": {"v": 1},
        "subject": SubjectMention(name="Acme Ltd", role="buyer"),
        "fingerprint": fp,
    }
    base.update(kw)
    return NewEvent.model_validate(base)


async def test_save_events_refuses_unverified_and_is_idempotent(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    async with maker() as s:
        d = await add_doc(s, "u", T0)
        ids = await ledger.save_claims(s, [mk(d, "ok"), mk(d, "bad", ClaimStatus.UNSUPPORTED)])
        concept = (await ledger.load_concepts(s))[0].id
        with pytest.raises(ledger.UnverifiedClaimError):
            await ledger.save_events(
                s,
                [new_event([ids["ok"]], "e0"), new_event([ids["ok"], ids["bad"]], "e1")],
            )
        with pytest.raises(ledger.UnverifiedClaimError):
            await ledger.save_events(s, [new_event([uuid4()], "e2")])
        with pytest.raises(ledger.UnverifiedClaimError):
            await ledger.save_events(s, [new_event([], "e2b")])
        assert await count(s, "events") == 0

        ev = new_event([ids["ok"]], "e3", concept_id=concept)
        first = await ledger.save_events(s, [ev])
        again = await ledger.save_events(s, [ev])
        assert first == again and await count(s, "events") == 1
        row = (await s.execute(text("SELECT * FROM events"))).mappings().one()
        assert row["description"] == "desc" and row["concept_id"] == concept
        assert row["cluster_id"] == ev.cluster_id and row["available_at"] == T0
        assert row["slots"]["city"] == "X" and row["details"] == {"v": 1}
        assert row["claim_ids"] == [ids["ok"]]


async def test_concepts(maker: async_sessionmaker[AsyncSession]) -> None:
    async with maker() as s:
        seeds = await ledger.load_concepts(s)
        assert len(seeds) == 13 and all(c.level == 0 for c in seeds)
        parent = seeds[0]
        a = ConceptAssignment(
            parent_id=parent.id,
            level=1,
            label="sub_kind",
            description="d",
            status="proposed",
            is_new=True,
        )
        first = await ledger.ensure_concept(s, a)
        assert await ledger.ensure_concept(s, a) == first
        top = ConceptAssignment(
            level=0, label=parent.label, description="x", status="active", is_new=False
        )
        assert await ledger.ensure_concept(s, top) == parent.id
        assert len(await ledger.load_concepts(s)) == 14  # 13 seeds + the new one
        assert len(await ledger.load_concepts(s, statuses=("retired",))) == 0
        await ledger.set_concept_embedding(s, first, [0.5] * 1024)
        got = {c.id: c for c in await ledger.load_concepts(s)}
        assert got[first].embedding is not None and len(got[first].embedding) == 1024


async def test_events_for_clustering(maker: async_sessionmaker[AsyncSession]) -> None:
    async with maker() as s:
        d = await add_doc(s, "u", T0)
        ids = await ledger.save_claims(s, [mk(d, "ok")])
        c = [ids["ok"]]
        await ledger.save_events(
            s,
            [
                new_event(c, "past"),
                new_event(c, "future", available_at=T0 + timedelta(days=3)),
                new_event(c, "undated", available_at=None, occurred_on=None, embedding=None),
            ],
        )
        everything = await ledger.events_for_clustering(
            s, event_type="facility_opened", occurred_from=None, occurred_to=None
        )
        assert len(everything) == 3
        windowed = await ledger.events_for_clustering(
            s,
            event_type="facility_opened",
            occurred_from=date(2026, 1, 1),
            occurred_to=date(2026, 3, 1),
        )
        assert len(windowed) == 2
        replay = await ledger.events_for_clustering(
            s, event_type="facility_opened", occurred_from=None, occurred_to=None, as_of=T0
        )
        assert len(replay) == 1
        assert replay[0].subject_key == "acme ltd" and len(replay[0].embedding or []) == 1024
        other = await ledger.events_for_clustering(
            s, event_type="nothing", occurred_from=None, occurred_to=None
        )
        assert other == []
