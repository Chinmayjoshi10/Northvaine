"""Save a finished radar run into the canonical schema (D86).

A run lives in memory and in its report files; this step makes it durable so feedback,
outcomes and learning can point at it:

- documents the run read (public; the id is the run's deterministic id when it is free)
- claims: every check of every document, verified or not, idempotent on fingerprint
- companies: one row per candidate key (`attributes.radar_key`); never for an unidentified
  subject or a natural person
- cases: one open case per company and window, stage `briefed`; a later run updates the
  verdict and appends to the trace, it never opens a duplicate or moves a case backwards
- case_evidence: the candidate's claims `for`, the skeptic's cited claims `against`
- case_open_questions: the skeptic's open questions, once each
- decisions: one `brief` row per gated candidate, briefed or rejected (propensity 1: the
  ranking is deterministic code)

Events are not saved yet: the radar's seeded concepts are not rows of `event_concepts`.
The caller owns the transaction (`session_scope` commits).
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any
from uuid import UUID

from pydantic import Field
from pydantic_core import to_jsonable_python

from northvaine.core.documents import ensure_source
from northvaine.core.ledger import save_claims
from northvaine.core.models import EvidenceDocument, LedgerResult, NorthvaineModel, SourceTier
from northvaine.radar.brief import action_status, caution
from northvaine.radar.models import (
    Candidate,
    RadarRun,
    RankedEntry,
    RejectedAs,
    RejectedEntry,
)
from northvaine.sensors.base import content_hash

__all__ = ["PersistResult", "persist_run"]

# A rejection that names no organisation never becomes a company row (privacy, D76).
_NO_COMPANY = {RejectedAs.UNIDENTIFIED, RejectedAs.NOT_AN_ORGANISATION}
_EARLY_STAGES = ("candidate", "gated", "investigated")


class PersistResult(NorthvaineModel):
    workspace_id: UUID
    documents_inserted: int
    claims: int
    companies: int
    cases: dict[str, UUID] = Field(default_factory=dict)  # candidate key -> case id
    decisions: int


def _text(sql: str) -> Any:
    from sqlalchemy import text

    return text(sql)


def _json(value: Any) -> str:
    return json.dumps(to_jsonable_python(value), sort_keys=True)


def _tier(source_name: str) -> SourceTier:
    from northvaine.sensors.registry import get_sensor

    try:
        return type(get_sensor(source_name)).tier
    except KeyError:
        return SourceTier.REPORTED


async def _workspace(session: Any, name: str) -> UUID:
    found = await session.execute(
        _text("SELECT id FROM workspaces WHERE name = :name ORDER BY created_at, id LIMIT 1"),
        {"name": name},
    )
    existing = found.scalar_one_or_none()
    if existing is not None:
        return existing
    created = await session.execute(
        _text("INSERT INTO workspaces (name) VALUES (:name) RETURNING id"), {"name": name}
    )
    return created.scalar_one()


async def _documents(
    session: Any, docs: Sequence[EvidenceDocument]
) -> tuple[dict[UUID, UUID], int]:
    """Insert each document once; returns run id -> stored id, and how many were new."""
    insert = _text(
        "INSERT INTO documents (id, source_id, url, content_hash, title, text, available_at, "
        "group_key, meta) VALUES (:id, :source_id, :url, :hash, :title, :text, :available_at, "
        ":group_key, CAST(:meta AS jsonb)) ON CONFLICT DO NOTHING RETURNING id"
    )
    lookup = _text("SELECT id FROM documents WHERE url = :url AND content_hash = :hash")
    sources: dict[str, UUID] = {}
    ids: dict[UUID, UUID] = {}
    inserted = 0
    for doc in docs:
        if doc.workspace_id is not None:
            raise ValueError("private documents are parked: persist_run saves public documents")
        if doc.id in ids:
            continue
        if doc.source_name not in sources:
            sources[doc.source_name] = await ensure_source(
                session, doc.source_name, _tier(doc.source_name)
            )
        digest = content_hash(doc.text)
        row = (
            await session.execute(
                insert,
                {
                    "id": doc.id,
                    "source_id": sources[doc.source_name],
                    "url": doc.url,
                    "hash": digest,
                    "title": doc.title,
                    "text": doc.text,
                    "available_at": doc.available_at,
                    "group_key": doc.group_key,
                    "meta": _json({**doc.meta, "source": doc.source_name}),
                },
            )
        ).first()
        if row is not None:
            inserted += 1
            ids[doc.id] = row[0]
            continue
        stored = (await session.execute(lookup, {"url": doc.url, "hash": digest})).first()
        if stored is None:  # the id was taken by a different page: keep that row's meaning
            raise ValueError(f"document id {doc.id} already names another page")
        ids[doc.id] = stored[0]
    return ids, inserted


async def _company(session: Any, candidate: Candidate) -> UUID:
    found = await session.execute(
        _text(
            "UPDATE companies SET name = :name, aliases = :aliases, updated_at = now() "
            "WHERE attributes->>'radar_key' = :key RETURNING id"
        ),
        {"key": candidate.key, "name": candidate.name, "aliases": candidate.aliases},
    )
    existing = found.scalar_one_or_none()
    if existing is not None:
        return existing
    created = await session.execute(
        _text(
            "INSERT INTO companies (name, aliases, country, attributes) "
            "VALUES (:name, :aliases, :country, CAST(:attributes AS jsonb)) RETURNING id"
        ),
        {
            "name": candidate.name,
            "aliases": candidate.aliases,
            "country": candidate.country,
            "attributes": _json({"radar_key": candidate.key}),
        },
    )
    return created.scalar_one()


def _verdict(entry: RankedEntry, run: RadarRun) -> dict[str, Any]:
    c = entry.candidate
    return {
        "as_of": run.as_of,
        "rank": entry.rank,
        "status": action_status(entry),
        "caution": caution(entry),
        "requirement": entry.requirement,
        "requirement_ref": entry.requirement_ref,
        "strength": entry.strength,
        "stream": c.stream.value,
        "rank_reasons": entry.rank_reasons,
        "window_note": c.window_note,
        "window_estimated": c.window_estimated,
        "steered": entry.steered,
        "gate": entry.gate,
        "skeptic": entry.skeptic,
        "likely_bidders": entry.likely_bidders,
    }


async def _case(
    session: Any, workspace_id: UUID, company_id: UUID, entry: RankedEntry, run: RadarRun
) -> UUID:
    c = entry.candidate
    trace = [
        {
            "at": run.as_of.isoformat(),
            "stage": "briefed",
            "rank": entry.rank,
            "status": action_status(entry),
            "gate": entry.gate.reason,
        }
    ]
    stage_list = ", ".join(f"'{s}'" for s in _EARLY_STAGES)
    result = await session.execute(
        _text(
            "INSERT INTO cases (workspace_id, company_id, direction, stage, verdict, "
            "window_start, window_end, trace) VALUES (:workspace_id, :company_id, 'outbound', "
            "'briefed', CAST(:verdict AS jsonb), :window_start, :window_end, "
            "CAST(:trace AS jsonb)) "
            "ON CONFLICT (workspace_id, company_id, pattern_id, window_start) "
            "WHERE stage NOT IN ('won','lost','dismissed') DO UPDATE SET "
            "verdict = EXCLUDED.verdict, window_end = EXCLUDED.window_end, "
            "trace = cases.trace || EXCLUDED.trace, updated_at = now(), "
            f"stage = CASE WHEN cases.stage IN ({stage_list}) THEN 'briefed' ELSE cases.stage END "
            "RETURNING id"
        ),
        {
            "workspace_id": workspace_id,
            "company_id": company_id,
            "verdict": _json(_verdict(entry, run)),
            "window_start": c.window_start,
            "window_end": c.window_end,
            "trace": _json(trace),
        },
    )
    return result.scalar_one()


async def _evidence(
    session: Any, case_id: UUID, entry: RankedEntry, claim_ids: dict[str, UUID]
) -> None:
    by_ref = {cl.ref: cl.fingerprint for cl in entry.candidate.claims}
    stances = {fp: "for" for fp in by_ref.values()}
    for point in entry.skeptic.against:
        if point.claim_ref in by_ref:
            stances[by_ref[point.claim_ref]] = "against"
    insert = _text(
        "INSERT INTO case_evidence (case_id, claim_id, stance) VALUES (:case_id, :claim_id, "
        ":stance) ON CONFLICT (case_id, claim_id) DO UPDATE SET stance = EXCLUDED.stance"
    )
    for fingerprint, stance in sorted(stances.items()):
        claim_id = claim_ids.get(fingerprint)
        if claim_id is None:
            raise ValueError(f"case claim {fingerprint} was not saved")
        await session.execute(insert, {"case_id": case_id, "claim_id": claim_id, "stance": stance})
    for question in entry.skeptic.open_questions:
        await session.execute(
            _text(
                "INSERT INTO case_open_questions (case_id, question, source_learner) "
                "SELECT :case_id, :question, 'research' WHERE NOT EXISTS (SELECT 1 FROM "
                "case_open_questions WHERE case_id = :case_id AND question = :question)"
            ),
            {"case_id": case_id, "question": question},
        )


def _features(candidate: Candidate) -> dict[str, Any]:
    return {
        "stream": candidate.stream.value,
        "streams": [s.value for s in candidate.streams],
        "country": candidate.country,
        "claims": len(candidate.claims),
        "documents": len({c.document_id for c in candidate.claims}),
        "events": len(candidate.events),
        "window_start": candidate.window_start,
    }


async def _decision(
    session: Any,
    workspace_id: UUID,
    *,
    case_id: UUID | None,
    company_id: UUID | None,
    features: dict[str, Any],
    choice: dict[str, Any],
) -> None:
    await session.execute(
        _text(
            "INSERT INTO decisions (workspace_id, kind, case_id, company_id, features, choice, "
            "propensity) VALUES (:workspace_id, 'brief', :case_id, :company_id, "
            "CAST(:features AS jsonb), CAST(:choice AS jsonb), 1)"
        ),
        {
            "workspace_id": workspace_id,
            "case_id": case_id,
            "company_id": company_id,
            "features": _json(features),
            "choice": _json(choice),
        },
    )


async def persist_run(
    session: Any,
    run: RadarRun,
    evidence: Sequence[tuple[EvidenceDocument, LedgerResult]],
    *,
    workspace_name: str | None = None,
) -> PersistResult:
    """Save `run` and the evidence it read (from `run_radar(evidence_out=...)`)."""
    workspace_id = await _workspace(session, workspace_name or run.client_id)
    doc_ids, inserted = await _documents(session, [doc for doc, _ in evidence])

    checks = [
        check.model_copy(update={"document_id": doc_ids[check.document_id]})
        for _, result in evidence
        for check in result.checks
    ]
    claim_ids = await save_claims(session, checks)

    companies: dict[str, UUID] = {}
    cases: dict[str, UUID] = {}
    decisions = 0
    for entry in run.entries:
        c = entry.candidate
        if c.key not in companies:
            companies[c.key] = await _company(session, c)
        case_id = await _case(session, workspace_id, companies[c.key], entry, run)
        cases[c.key] = case_id
        await _evidence(session, case_id, entry, claim_ids)
        await _decision(
            session,
            workspace_id,
            case_id=case_id,
            company_id=companies[c.key],
            features={**_features(c), "as_of": run.as_of, "strength": entry.strength},
            choice={
                "briefed": True,
                "rank": entry.rank,
                "status": action_status(entry),
                "requirement": entry.requirement,
            },
        )
        decisions += 1
    for rejected in run.rejected:
        decisions += await _rejection(session, workspace_id, rejected, run, companies)
    return PersistResult(
        workspace_id=workspace_id,
        documents_inserted=inserted,
        claims=len(claim_ids),
        companies=len(companies),
        cases=cases,
        decisions=decisions,
    )


async def _rejection(
    session: Any,
    workspace_id: UUID,
    rejected: RejectedEntry,
    run: RadarRun,
    companies: dict[str, UUID],
) -> int:
    c, gate = rejected.candidate, rejected.gate
    company_id: UUID | None = None
    if gate.rejected_as not in _NO_COMPANY:
        if c.key not in companies:
            companies[c.key] = await _company(session, c)
        company_id = companies[c.key]
    await _decision(
        session,
        workspace_id,
        case_id=None,
        company_id=company_id,
        features={**_features(c), "as_of": run.as_of},
        choice={
            "briefed": False,
            "rejected_as": gate.rejected_as.value if gate.rejected_as else None,
            "by": gate.by,
            "reason": gate.reason if company_id is not None else None,
        },
    )
    return 1
