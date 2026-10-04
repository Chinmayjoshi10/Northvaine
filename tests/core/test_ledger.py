"""Offline tests for the ledger store (T4.4): SQL parameter shapes and the refusal path."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest

from northvaine.core import ledger
from northvaine.core.models import (
    ClaimCheck,
    ClaimDraft,
    ClaimStatus,
    ConceptAssignment,
    NewEvent,
    SubjectMention,
)


class FakeResult:
    def __init__(self, rows: list[Any] | None = None) -> None:
        self.rows = rows or []

    def all(self) -> list[Any]:
        return self.rows

    def mappings(self) -> list[Any]:
        return self.rows

    def scalar_one_or_none(self) -> Any:
        return self.rows[0][0] if self.rows else None

    def scalar_one(self) -> Any:
        return self.rows[0][0]


class FakeSession:
    def __init__(self, *results: FakeResult) -> None:
        self.results = list(results)
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def execute(self, stmt: Any, params: dict[str, Any] | None = None) -> FakeResult:
        self.calls.append((str(stmt), params or {}))
        return self.results.pop(0) if self.results else FakeResult()


def check(status: ClaimStatus = ClaimStatus.VERIFIED, fp: str = "f1") -> ClaimCheck:
    ok = status == ClaimStatus.VERIFIED
    return ClaimCheck(
        document_id=uuid4(),
        draft=ClaimDraft(
            statement="s",
            source_quote="q",
            subject=SubjectMention(name="Acme", country="DE", role="buyer"),
            extracted_by="m",
            meta={"note": 1},
        ),
        status=status,
        quote_offset=3 if ok else None,
        verified_by="code" if ok else None,
        fingerprint=fp,
    )


def event(claim_ids: list[UUID], fp: str = "e1") -> NewEvent:
    return NewEvent(
        event_type="facility_opened",
        claim_ids=claim_ids,
        occurred_on=date(2026, 1, 2),
        description="d",
        embedding=[0.5, 1.0],
        cluster_id=uuid4(),
        slots={"k": "v"},
        subject=SubjectMention(name="Acme", role="buyer"),
        fingerprint=fp,
    )


async def test_save_claims_params_and_mapping() -> None:
    cid = uuid4()
    session = FakeSession(FakeResult(), FakeResult([("f1", cid)]))
    c = check()
    out = await ledger.save_claims(session, [c])  # type: ignore[arg-type]
    assert out == {"f1": cid}
    sql, params = session.calls[0]
    assert "ON CONFLICT (fingerprint) DO NOTHING" in sql
    assert params["status"] == "verified" and params["verified"] is True
    assert params["quote_offset"] == 3 and params["verified_by"] == "code"
    assert '"subject"' in params["meta"] and '"note": 1' in params["meta"]
    assert session.calls[1][1] == {"fps": ["f1"]}


async def test_save_claims_rejected_is_stored_unverified() -> None:
    session = FakeSession()
    await ledger.save_claims(session, [check(ClaimStatus.QUOTE_NOT_FOUND)])  # type: ignore[arg-type]
    params = session.calls[0][1]
    assert params["verified"] is False and params["quote_offset"] is None


async def test_save_claims_empty_does_no_sql() -> None:
    session = FakeSession()
    assert await ledger.save_claims(session, []) == {}  # type: ignore[arg-type]
    assert session.calls == []


async def test_save_events_refuses_unverified_and_inserts_nothing() -> None:
    good, bad = uuid4(), uuid4()
    session = FakeSession(FakeResult([(good,)]))
    with pytest.raises(ledger.UnverifiedClaimError, match=str(bad)):
        await ledger.save_events(session, [event([good, bad])])  # type: ignore[arg-type]
    assert len(session.calls) == 1
    assert "verified_claims" in session.calls[0][0]


async def test_save_events_inserts_with_subject_in_slots() -> None:
    cid, eid = uuid4(), uuid4()
    session = FakeSession(FakeResult([(cid,)]), FakeResult(), FakeResult([("e1", eid)]))
    out = await ledger.save_events(session, [event([cid])])  # type: ignore[arg-type]
    assert out == {"e1": eid}
    sql, params = session.calls[1]
    assert "ON CONFLICT (fingerprint) DO NOTHING" in sql
    assert params["embedding"] == "[0.5,1.0]"
    assert params["claim_ids"] == [str(cid)]
    assert '"subject"' in params["slots"] and '"k": "v"' in params["slots"]


async def test_verified_claims_filters() -> None:
    session = FakeSession()
    ws, doc = uuid4(), uuid4()
    as_of = datetime(2026, 1, 1, tzinfo=UTC)
    await ledger.verified_claims(
        session,
        document_ids=[doc],
        as_of=as_of,
        workspace_id=ws,  # type: ignore[arg-type]
    )
    sql, params = session.calls[0]
    assert "FROM verified_claims" in sql
    assert "workspace_id IS NULL OR" in sql
    assert "available_at IS NOT NULL AND available_at <= :as_of" in sql
    assert params["document_ids"] == [str(doc)] and params["workspace_id"] == ws
    assert params["as_of"] == as_of


async def test_verified_claims_public_only_and_no_as_of() -> None:
    session = FakeSession()
    await ledger.verified_claims(session)  # type: ignore[arg-type]
    sql, params = session.calls[0]
    assert params == {"workspace_id": None}
    assert "as_of" not in sql


async def test_ensure_concept_returns_existing_without_insert() -> None:
    existing = uuid4()
    session = FakeSession(FakeResult([(existing,)]))
    a = ConceptAssignment(level=0, label="x", description="d", status="active", is_new=False)
    assert await ledger.ensure_concept(session, a) == existing  # type: ignore[arg-type]
    assert len(session.calls) == 1


async def test_ensure_concept_inserts_when_missing() -> None:
    new = uuid4()
    session = FakeSession(FakeResult(), FakeResult(), FakeResult([(new,)]))
    a = ConceptAssignment(
        level=1,
        parent_id=uuid4(),
        label="x",
        description="d",
        status="proposed",
        is_new=True,
        embedding=[1.0],
    )
    assert await ledger.ensure_concept(session, a) == new  # type: ignore[arg-type]
    assert session.calls[1][1]["embedding"] == "[1.0]"


async def test_events_for_clustering_window_and_as_of() -> None:
    session = FakeSession()
    await ledger.events_for_clustering(
        session,  # type: ignore[arg-type]
        event_type="t",
        occurred_from=date(2026, 1, 1),
        occurred_to=None,
        as_of=datetime(2026, 2, 1, tzinfo=UTC),
        limit=5,
    )
    sql, params = session.calls[0]
    assert "occurred_on >= :occurred_from" in sql and "occurred_to" not in sql
    assert "available_at IS NOT NULL" in sql
    assert params["limit"] == 5


async def test_events_for_clustering_open_window_has_no_date_filter() -> None:
    session = FakeSession()
    await ledger.events_for_clustering(
        session,
        event_type="t",
        occurred_from=None,
        occurred_to=None,  # type: ignore[arg-type]
    )
    sql = session.calls[0][0]
    assert "occurred_on >=" not in sql and "occurred_on <=" not in sql
    assert "available_at" in sql  # selected, not filtered
    assert "available_at IS NOT NULL" not in sql


async def test_events_for_clustering_maps_rows() -> None:
    eid = uuid4()
    row = {
        "id": eid,
        "cluster_id": None,
        "event_type": "t",
        "occurred_on": None,
        "slots": {"subject": {"name": " Acme "}, "group_key": "g"},
        "details": {},
        "embedding": "[1.0,2.5]",
        "available_at": None,
    }
    session = FakeSession(FakeResult([row]))
    [c] = await ledger.events_for_clustering(
        session,
        event_type="t",
        occurred_from=None,
        occurred_to=None,  # type: ignore[arg-type]
    )
    assert c.cluster_id == eid and c.subject_key == "acme" and c.group_key == "g"
    assert c.embedding == [1.0, 2.5]


def test_vector_roundtrip() -> None:
    assert ledger._parse_vector(ledger._vector_literal([0.25, 1.0])) == [0.25, 1.0]
    assert ledger._vector_literal(None) is None
    assert ledger._parse_vector(None) is None
