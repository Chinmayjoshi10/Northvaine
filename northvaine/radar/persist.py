"""Save a finished radar run into the canonical schema (D86).

A run lives in memory and in its report files; this step makes it durable so feedback,
outcomes and learning can point at it:

- documents the run read (public; the id is the run's deterministic id when it is free)
- claims: every check of every document, verified or not, idempotent on fingerprint
- companies: one row per match key, found through `company_identifiers` (scheme
  `name_country`, D88); never for an unidentified subject or a natural person
- links: the web of who did what in which buying process (`radar/graph.py`, D88)
- cases: one open case per company and window, stage `briefed`; a later run updates the
  verdict and appends to the trace, it never opens a duplicate or moves a case backwards
- case_evidence: the candidate's claims `for`, the skeptic's cited claims `against`
- case_open_questions: the skeptic's open questions, once each
- events: every event the ledger grounded, with its concept mapped from the radar's seeded
  ids to the database's rows by label (D87), and linked to its company once known
- decisions: one `brief` row per gated candidate, briefed or rejected, with the sources and
  the queries ("sensor:index") that found its evidence (D87). Propensity 1: the ranking is
  deterministic code.

The caller owns the transaction (`session_scope` commits).
"""

from __future__ import annotations

import contextlib
import json
from collections.abc import Sequence
from typing import Any
from uuid import UUID

from pydantic import Field
from pydantic_core import to_jsonable_python

from northvaine.core.documents import ensure_source
from northvaine.core.ledger import ensure_concept, load_concepts, save_claims, save_events
from northvaine.core.models import (
    EvidenceDocument,
    LedgerResult,
    NewEvent,
    NorthvaineModel,
    SourceTier,
)
from northvaine.core.settings import Settings, get_settings
from northvaine.radar.brief import action_status, caution
from northvaine.radar.graph import bidder_links, save_links, stated_links
from northvaine.radar.learning import query_keys_by_ref
from northvaine.radar.models import (
    Candidate,
    RadarRun,
    RankedEntry,
    RejectedAs,
    RejectedEntry,
)
from northvaine.sensors.base import content_hash

__all__ = ["PersistResult", "persist_run", "provenance"]

# A rejection that names no organisation never becomes a company row (privacy, D76).
_NO_COMPANY = {RejectedAs.UNIDENTIFIED, RejectedAs.NOT_AN_ORGANISATION}
_EARLY_STAGES = ("candidate", "gated", "investigated")


class PersistResult(NorthvaineModel):
    workspace_id: UUID
    documents_inserted: int
    claims: int
    events: int
    companies: int
    links: int
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
    """Insert each document once, in one batch; returns run id -> stored id, and how many were
    new. A page already stored under the same (url, content hash) keeps its row."""
    unique: dict[UUID, tuple[EvidenceDocument, str]] = {}
    for doc in docs:
        if doc.workspace_id is not None:
            raise ValueError("private documents are parked: persist_run saves public documents")
        unique.setdefault(doc.id, (doc, content_hash(doc.text)))
    if not unique:
        return {}, 0
    sources: dict[str, UUID] = {}
    for doc, _ in unique.values():
        if doc.source_name not in sources:
            sources[doc.source_name] = await ensure_source(
                session, doc.source_name, _tier(doc.source_name)
            )
    pairs = sorted({(doc.url, digest) for doc, digest in unique.values()})
    lookup = _text(
        "SELECT d.id, d.url, d.content_hash FROM documents d "
        "JOIN unnest(CAST(:urls AS text[]), CAST(:hashes AS text[])) AS p(url, hash) "
        "ON d.url = p.url AND d.content_hash = p.hash"
    )
    params = {"urls": [u for u, _ in pairs], "hashes": [h for _, h in pairs]}
    before = {(r.url, r.content_hash): r.id for r in (await session.execute(lookup, params))}
    rows = [
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
        }
        for doc, digest in unique.values()
        if (doc.url, digest) not in before
    ]
    if rows:
        await session.execute(
            _text(
                "INSERT INTO documents (id, source_id, url, content_hash, title, text, "
                "available_at, group_key, meta) VALUES (:id, :source_id, :url, :hash, :title, "
                ":text, :available_at, :group_key, CAST(:meta AS jsonb)) ON CONFLICT DO NOTHING"
            ),
            rows,
        )
    after = {(r.url, r.content_hash): r.id for r in (await session.execute(lookup, params))}
    ids: dict[UUID, UUID] = {}
    for doc_id, (doc, digest) in unique.items():
        stored = after.get((doc.url, digest))
        if stored is None:  # the id was taken by a different page: keep that row's meaning
            raise ValueError(f"document id {doc_id} already names another page")
        ids[doc_id] = stored
    return ids, len(after) - len(before)


_MATCH_SCHEME = "name_country"  # the normalised name and country key (D58, D88)


async def _company_by_key(
    session: Any, key: str, name: str, country: str | None, aliases: Sequence[str] = ()
) -> UUID:
    """The company holding identifier (`name_country`, key), created with it if new."""
    found = await session.execute(
        _text("SELECT company_id FROM company_identifiers WHERE scheme = :scheme AND value = :key"),
        {"scheme": _MATCH_SCHEME, "key": key},
    )
    existing = found.scalar_one_or_none()
    if existing is not None:
        if aliases:
            await session.execute(
                _text(
                    "UPDATE companies SET aliases = (SELECT array_agg(DISTINCT a ORDER BY a) "
                    "FROM unnest(aliases || CAST(:aliases AS text[])) AS a), updated_at = now() "
                    "WHERE id = :id"
                ),
                {"id": existing, "aliases": list(aliases)},
            )
        return existing
    created = await session.execute(
        _text(
            "INSERT INTO companies (name, aliases, country) VALUES (:name, :aliases, :country) "
            "RETURNING id"
        ),
        {"name": name, "aliases": list(aliases), "country": country},
    )
    company_id = created.scalar_one()
    await session.execute(
        _text(
            "INSERT INTO company_identifiers (company_id, scheme, value) "
            "VALUES (:company_id, :scheme, :key)"
        ),
        {"company_id": company_id, "scheme": _MATCH_SCHEME, "key": key},
    )
    return company_id


async def _company(session: Any, candidate: Candidate) -> UUID:
    return await _company_by_key(
        session, candidate.key, candidate.name, candidate.country, candidate.aliases
    )


def _verdict(entry: RankedEntry, run: RadarRun) -> dict[str, Any]:
    c = entry.candidate
    return {
        "as_of": run.as_of,
        "rank": entry.rank,
        "status": action_status(entry),
        "caution": caution(entry),
        "requirement": entry.requirement,
        "requirement_ref": entry.requirement_ref,
        "evidence_level": entry.evidence_level,
        "account_role": entry.account_role,
        "contract_nature": entry.contract_nature,
        "nature_derived": entry.nature_derived,
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


async def _events(
    session: Any,
    evidence: Sequence[tuple[EvidenceDocument, LedgerResult]],
    doc_ids: dict[UUID, UUID],
    claim_ids: dict[str, UUID],
) -> dict[str, UUID]:
    """Save every grounded event; returns fingerprint -> id. The radar runs on seeded concepts
    whose ids are not database rows, so each is mapped by label to the stored level-0 row, and
    a new finer concept is created under that row."""
    pending = [event for _, result in evidence for event in result.events]
    if not pending:
        return {}
    stored = {c.label: c.id for c in await load_concepts(session) if c.level == 0}
    seeded = {}
    for event in pending:
        concept = event.concept
        if concept.level == 0 and concept.concept_id is not None:
            seeded[concept.concept_id] = concept.label
    new_events: list[NewEvent] = []
    for event in pending:
        concept = event.concept
        if concept.level == 0:
            concept_id = stored.get(concept.label)
        else:
            parent_label = seeded.get(concept.parent_id) if concept.parent_id else None
            parent = stored.get(parent_label or event.event_type)
            concept_id = (
                await ensure_concept(session, concept.model_copy(update={"parent_id": parent}))
                if parent is not None
                else stored.get(event.event_type)
            )
        details = dict(event.details)
        if "document_id" in details:
            with contextlib.suppress(KeyError, ValueError):
                details["document_id"] = str(doc_ids[UUID(str(details["document_id"]))])
        new_events.append(
            NewEvent(
                event_type=event.event_type,
                claim_ids=[claim_ids[fp] for fp in event.claim_fingerprints],
                occurred_on=event.occurred_on,
                available_at=event.available_at,
                subject=event.subject,
                description=event.description,
                embedding=event.embedding,
                concept_id=concept_id,
                cluster_id=event.cluster_id,
                slots=event.slots,
                details=details,
                fingerprint=event.fingerprint,
            )
        )
    return await save_events(session, new_events)


async def _link_events(session: Any, candidate: Candidate, company_id: UUID) -> None:
    fingerprints = sorted({e.fingerprint for e in candidate.events})
    if fingerprints:
        await session.execute(
            _text(
                "UPDATE events SET company_id = :company_id WHERE company_id IS NULL "
                "AND fingerprint = ANY(CAST(:fps AS text[]))"
            ),
            {"company_id": company_id, "fps": fingerprints},
        )


def provenance(candidate: Candidate, run: RadarRun) -> dict[str, Any]:
    """The sources and the queries ("sensor:index") behind a candidate's evidence (D87)."""
    queries = sorted(
        {ref for c in candidate.claims for ref in run.found_by.get(str(c.document_id), [])}
    )
    by_ref = query_keys_by_ref(run.queries)
    keys = {by_ref[ref] for ref in queries if ref in by_ref}
    return {
        "sources": sorted({c.source_name for c in candidate.claims}),
        "queries": queries,
        "query_propensity": {
            q: run.query_propensity[q] for q in queries if q in run.query_propensity
        },
        "query_keys": sorted(keys),  # stable across runs and clients (D89)
    }


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
    propensity: float = 1.0,
) -> None:
    await session.execute(
        _text(
            "INSERT INTO decisions (workspace_id, kind, case_id, company_id, features, choice, "
            "propensity) VALUES (:workspace_id, 'brief', :case_id, :company_id, "
            "CAST(:features AS jsonb), CAST(:choice AS jsonb), :propensity)"
        ),
        {
            "workspace_id": workspace_id,
            "case_id": case_id,
            "company_id": company_id,
            "features": _json(features),
            "choice": _json(choice),
            "propensity": propensity,
        },
    )


async def persist_run(
    session: Any,
    run: RadarRun,
    evidence: Sequence[tuple[EvidenceDocument, LedgerResult]],
    *,
    workspace_name: str | None = None,
    settings: Settings | None = None,
) -> PersistResult:
    """Save `run` and the evidence it read (from `run_radar(evidence_out=...)`)."""
    settings = settings or get_settings()
    workspace_id = await _workspace(session, workspace_name or run.client_id)
    doc_ids, inserted = await _documents(session, [doc for doc, _ in evidence])

    checks = [
        check.model_copy(update={"document_id": doc_ids[check.document_id]})
        for _, result in evidence
        for check in result.checks
    ]
    claim_ids = await save_claims(session, checks)
    event_ids = await _events(session, evidence, doc_ids, claim_ids)

    companies: dict[str, UUID] = {}
    cases: dict[str, UUID] = {}
    decisions = 0
    for entry in run.entries:
        c = entry.candidate
        if c.key not in companies:
            companies[c.key] = await _company(session, c)
        await _link_events(session, c, companies[c.key])
        case_id = await _case(session, workspace_id, companies[c.key], entry, run)
        cases[c.key] = case_id
        await _evidence(session, case_id, entry, claim_ids)
        await _decision(
            session,
            workspace_id,
            case_id=case_id,
            company_id=companies[c.key],
            features={
                **_features(c),
                **provenance(c, run),
                "as_of": run.as_of,
                "strength": entry.strength,
            },
            choice={
                "briefed": True,
                "rank": entry.rank,
                "status": action_status(entry),
                "requirement": entry.requirement,
                "exploration": entry.exploration,
            },
            propensity=entry.propensity,
        )
        decisions += 1
    for rejected in run.rejected:
        decisions += await _rejection(session, workspace_id, rejected, run, companies)

    # The web (D88): who did what in which buying process. Never a node for a natural person
    # or for a subject the gate found is not an organisation.
    hidden = {r.candidate.key for r in run.rejected if r.gate.rejected_as in _NO_COMPANY}

    async def company_for(key: str, name: str, country: str | None) -> UUID:
        if key not in companies:
            companies[key] = await _company_by_key(session, key, name, country)
        return companies[key]

    pending = await stated_links(
        evidence, company_for=company_for, hidden_keys=hidden, settings=settings
    )
    pending += await bidder_links(run, evidence, company_for=company_for, settings=settings)
    links = await save_links(session, pending, claim_ids)
    return PersistResult(
        workspace_id=workspace_id,
        documents_inserted=inserted,
        claims=len(claim_ids),
        events=len(event_ids),
        companies=len(companies),
        links=links,
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
        await _link_events(session, c, company_id)
    await _decision(
        session,
        workspace_id,
        case_id=None,
        company_id=company_id,
        features={**_features(c), **provenance(c, run), "as_of": run.as_of},
        choice={
            "briefed": False,
            "rejected_as": gate.rejected_as.value if gate.rejected_as else None,
            "by": gate.by,
            "reason": gate.reason if company_id is not None else None,
        },
    )
    return 1
