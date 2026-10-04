"""Ledger store: the ONLY module that touches the `claims` table (T4.4, D49).

Consumers read verified claims through `verified_claims` (the SQL view). Check_invariants rules
keep SQL on `claims` and `ClaimRow` imports inside this file.

No function commits: the caller owns the transaction. Vectors are bound as the pgvector text
form (`[0.1,0.2]`) and cast in SQL, so no adapter dependency is needed. Event subjects are
stored inside `slots["subject"]` (events has no subject column); the clustering subject key is
read back from there.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import date, datetime
from typing import Any
from uuid import UUID

from pydantic_core import to_jsonable_python

from northvaine.core.models import (
    ClaimCheck,
    ClusterCandidate,
    ConceptAssignment,
    EventConceptRow,
    NewEvent,
    VerifiedClaim,
)

__all__ = [
    "UnverifiedClaimError",
    "ensure_concept",
    "events_for_clustering",
    "load_concepts",
    "save_claims",
    "save_events",
    "set_concept_embedding",
    "verified_claims",
]


class UnverifiedClaimError(ValueError):
    """`save_events` was given a claim id that is not verified."""


def _text(sql: str) -> Any:
    from sqlalchemy import text

    return text(sql)


def _vector_literal(vector: Sequence[float] | None) -> str | None:
    if vector is None:
        return None
    return "[" + ",".join(repr(float(x)) for x in vector) + "]"


def _parse_vector(raw: Any) -> list[float] | None:
    if raw is None:
        return None
    if isinstance(raw, str):
        inner = raw.strip().removeprefix("[").removesuffix("]")
        return [float(x) for x in inner.split(",")] if inner else []
    return [float(x) for x in raw]


def _json(value: Any) -> str:
    return json.dumps(to_jsonable_python(value))


def _claim_meta(check: ClaimCheck) -> dict[str, Any]:
    meta: dict[str, Any] = dict(to_jsonable_python(check.draft.meta))
    if check.draft.subject is not None:
        meta["subject"] = to_jsonable_python(check.draft.subject)
    return meta


def _subject_key(slots: dict[str, Any]) -> str | None:
    subject = slots.get("subject", slots.get("subject_key"))
    if isinstance(subject, dict):
        subject = subject.get("name")
    if isinstance(subject, str) and subject.strip():
        return subject.strip().casefold()
    return None


async def save_claims(session: Any, checks: list[ClaimCheck]) -> dict[str, UUID]:
    """Store every check (verified or rejected) idempotently on fingerprint; returns
    fingerprint -> id."""
    if not checks:
        return {}
    insert = _text(
        "INSERT INTO claims (document_id, statement, source_quote, quote_offset, verified, "
        "verified_by, extracted_by, status, meta, fingerprint) "
        "VALUES (:document_id, :statement, :source_quote, :quote_offset, :verified, "
        ":verified_by, :extracted_by, :status, CAST(:meta AS jsonb), :fingerprint) "
        "ON CONFLICT (fingerprint) DO NOTHING"
    )
    for check in checks:
        await session.execute(
            insert,
            {
                "document_id": check.document_id,
                "statement": check.draft.statement,
                "source_quote": check.draft.source_quote,
                "quote_offset": check.quote_offset,
                "verified": check.verified,
                "verified_by": check.verified_by,
                "extracted_by": check.draft.extracted_by,
                "status": check.status.value,
                "meta": _json(_claim_meta(check)),
                "fingerprint": check.fingerprint,
            },
        )
    fingerprints = sorted({c.fingerprint for c in checks})
    result = await session.execute(
        _text("SELECT fingerprint, id FROM claims WHERE fingerprint = ANY(CAST(:fps AS text[]))"),
        {"fps": fingerprints},
    )
    return {row[0]: row[1] for row in result.all()}


async def verified_claims(
    session: Any,
    *,
    document_ids: Sequence[UUID] | None = None,
    as_of: datetime | None = None,
    workspace_id: UUID | None = None,
) -> list[VerifiedClaim]:
    """Read the `verified_claims` view: public claims plus, when given, that workspace's.
    With `as_of`, only `available_at <= as_of` (NULL excluded)."""
    where = ["(workspace_id IS NULL OR workspace_id = CAST(:workspace_id AS uuid))"]
    params: dict[str, Any] = {"workspace_id": workspace_id}
    if document_ids is not None:
        where.append("document_id = ANY(CAST(:document_ids AS uuid[]))")
        params["document_ids"] = [str(d) for d in document_ids]
    if as_of is not None:
        where.append("available_at IS NOT NULL AND available_at <= :as_of")
        params["as_of"] = as_of
    result = await session.execute(
        _text(
            "SELECT id, document_id, statement, source_quote, quote_offset, verified_by, "
            "available_at, workspace_id, meta FROM verified_claims "
            f"WHERE {' AND '.join(where)} ORDER BY created_at, id"
        ),
        params,
    )
    return [VerifiedClaim.model_validate(dict(row)) for row in result.mappings()]


async def load_concepts(
    session: Any, *, statuses: Sequence[str] = ("active", "proposed")
) -> list[EventConceptRow]:
    """The concept tree rows with one of `statuses`."""
    result = await session.execute(
        _text(
            "SELECT id, parent_id, level, label, description, embedding::text AS embedding, "
            "status, merged_into, created_at FROM event_concepts "
            "WHERE status = ANY(CAST(:statuses AS text[])) ORDER BY level, label, id"
        ),
        {"statuses": list(statuses)},
    )
    rows = []
    for row in result.mappings():
        data = dict(row)
        data["embedding"] = _parse_vector(data["embedding"])
        rows.append(EventConceptRow.model_validate(data))
    return rows


async def ensure_concept(session: Any, assignment: ConceptAssignment) -> UUID:
    """The id of the concept, created if new; idempotent on (parent_id, label)."""
    find = _text(
        "SELECT id FROM event_concepts "
        "WHERE parent_id IS NOT DISTINCT FROM CAST(:parent_id AS uuid) AND label = :label"
    )
    params = {"parent_id": assignment.parent_id, "label": assignment.label}
    found = (await session.execute(find, params)).scalar_one_or_none()
    if found is not None:
        return found
    await session.execute(
        _text(
            "INSERT INTO event_concepts (parent_id, level, label, description, embedding, status) "
            "VALUES (CAST(:parent_id AS uuid), :level, :label, :description, "
            "CAST(:embedding AS vector), :status) ON CONFLICT DO NOTHING"
        ),
        {
            **params,
            "level": assignment.level,
            "description": assignment.description,
            "embedding": _vector_literal(assignment.embedding),
            "status": assignment.status,
        },
    )
    return (await session.execute(find, params)).scalar_one()


async def set_concept_embedding(session: Any, concept_id: UUID, embedding: Sequence[float]) -> None:
    """Store an embedding on a concept."""
    await session.execute(
        _text("UPDATE event_concepts SET embedding = CAST(:embedding AS vector) WHERE id = :id"),
        {"embedding": _vector_literal(embedding), "id": concept_id},
    )


async def save_events(session: Any, events: list[NewEvent]) -> dict[str, UUID]:
    """Insert events with ON CONFLICT (fingerprint) DO NOTHING; returns fingerprint -> id.
    Raises `UnverifiedClaimError` if any claim id is not verified; nothing is inserted then."""
    if not events:
        return {}
    wanted = {cid for event in events for cid in event.claim_ids}
    if wanted:
        result = await session.execute(
            _text("SELECT id FROM verified_claims WHERE id = ANY(CAST(:ids AS uuid[]))"),
            {"ids": sorted(str(c) for c in wanted)},
        )
        good = {str(r[0]) for r in result.all()}
        bad = sorted(str(c) for c in wanted if str(c) not in good)
        if bad:
            raise UnverifiedClaimError(f"claims not verified or missing: {', '.join(bad)}")
    insert = _text(
        "INSERT INTO events (event_type, occurred_on, details, cluster_id, claim_ids, concept_id, "
        "slots, available_at, description, embedding, fingerprint) "
        "VALUES (:event_type, :occurred_on, CAST(:details AS jsonb), :cluster_id, "
        "CAST(:claim_ids AS uuid[]), :concept_id, CAST(:slots AS jsonb), :available_at, "
        ":description, CAST(:embedding AS vector), :fingerprint) "
        "ON CONFLICT (fingerprint) DO NOTHING"
    )
    for event in events:
        slots = dict(event.slots)
        if event.subject is not None and "subject" not in slots:
            slots["subject"] = to_jsonable_python(event.subject)
        await session.execute(
            insert,
            {
                "event_type": event.event_type,
                "occurred_on": event.occurred_on,
                "details": _json(event.details),
                "cluster_id": event.cluster_id,
                "claim_ids": [str(c) for c in event.claim_ids],
                "concept_id": event.concept_id,
                "slots": _json(slots),
                "available_at": event.available_at,
                "description": event.description,
                "embedding": _vector_literal(event.embedding),
                "fingerprint": event.fingerprint,
            },
        )
    fingerprints = sorted({e.fingerprint for e in events})
    result = await session.execute(
        _text("SELECT fingerprint, id FROM events WHERE fingerprint = ANY(CAST(:fps AS text[]))"),
        {"fps": fingerprints},
    )
    return {row[0]: row[1] for row in result.all()}


async def events_for_clustering(
    session: Any,
    *,
    event_type: str,
    occurred_from: date | None,
    occurred_to: date | None,
    as_of: datetime | None = None,
    limit: int = 200,
) -> list[ClusterCandidate]:
    """Recent events of one type for dedup. With `as_of`, `available_at <= as_of` and NULL
    excluded. A bounded window excludes events with NULL `occurred_on`."""
    where = ["event_type = :event_type"]
    params: dict[str, Any] = {"event_type": event_type, "limit": limit}
    if occurred_from is not None:
        where.append("occurred_on >= :occurred_from")
        params["occurred_from"] = occurred_from
    if occurred_to is not None:
        where.append("occurred_on <= :occurred_to")
        params["occurred_to"] = occurred_to
    if as_of is not None:
        where.append("available_at IS NOT NULL AND available_at <= :as_of")
        params["as_of"] = as_of
    result = await session.execute(
        _text(
            "SELECT id, cluster_id, event_type, occurred_on, slots, details, "
            "embedding::text AS embedding, available_at FROM events "
            f"WHERE {' AND '.join(where)} "
            "ORDER BY occurred_on DESC NULLS LAST, created_at DESC, id LIMIT :limit"
        ),
        params,
    )
    out: list[ClusterCandidate] = []
    for row in result.mappings():
        slots = row["slots"] or {}
        details = row["details"] or {}
        group_key = slots.get("group_key", details.get("group_key"))
        out.append(
            ClusterCandidate(
                event_id=row["id"],
                cluster_id=row["cluster_id"] or row["id"],
                event_type=row["event_type"],
                occurred_on=row["occurred_on"],
                subject_key=_subject_key(slots),
                group_key=group_key if isinstance(group_key, str) else None,
                embedding=_parse_vector(row["embedding"]),
                available_at=row["available_at"],
            )
        )
    return out
