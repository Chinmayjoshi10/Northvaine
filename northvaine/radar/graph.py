"""Graph v0: connect the dots (D88).

The web lives in Postgres: nodes are existing rows (a company, an event) or a procedure (one
buying process, addressed by '<source>:<the source's own id>'), and lines are rows of `links`.
Every line is backed by verified claims, checked by code before it is written (CLAUDE.md #2).
No model ever proposes a line.

Lines written by a run:
- **stated:** a company -[role]-> procedure, from an official record's own Buyer or Winner line
  (the role comes from the structured record).
- **inferred:** procedure -[likely_bidder]-> company, for an open tender whose likely bidder won
  similar awards (D81). The claims are those verified winner lines. The confidence is a plain
  heuristic from the number of wins and says so in `details`.

Reads return a small view (nodes and edges, each edge with its quotes and source links) for
the brief, the API and the frontend.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable, Sequence
from datetime import date, datetime
from typing import Any
from uuid import UUID

from pydantic import Field

from northvaine.core.models import (
    EvidenceDocument,
    LedgerResult,
    LinkDerivation,
    NodeKind,
    NorthvaineModel,
)
from northvaine.core.settings import Settings
from northvaine.radar.entities import company_key
from northvaine.radar.models import RadarRun

__all__ = [
    "GraphEdge",
    "GraphNode",
    "GraphView",
    "PendingLink",
    "bidder_links",
    "link_fingerprint",
    "neighbourhood",
    "procedure_id",
    "save_links",
    "stated_links",
]

_WINNER_PREFIX = "Winner ["
_WITHHELD = "["  # natural persons are withheld as "[...]" (D76): never a node

CompanyFor = Callable[[str, str, str | None], Awaitable[UUID]]  # key, name, country -> id


def procedure_id(doc: EvidenceDocument) -> str | None:
    """The procedure node of a document: its source and its own grouping id, or None."""
    return f"{doc.source_name}:{doc.group_key}" if doc.group_key else None


def link_fingerprint(
    src: tuple[NodeKind, str],
    dst: tuple[NodeKind, str],
    relation: str,
    derivation: LinkDerivation,
    workspace_id: UUID | None = None,
) -> str:
    """One line per (ends, relation, derivation, workspace): more evidence for the same line
    is added to it, never written as a second line."""
    payload = json.dumps(
        [src[0].value, src[1], dst[0].value, dst[1], relation, derivation.value, str(workspace_id)]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class PendingLink(NorthvaineModel):
    src_kind: NodeKind
    src_id: str
    dst_kind: NodeKind
    dst_id: str
    relation: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    derivation: LinkDerivation
    claim_fingerprints: list[str] = Field(min_length=1)
    confidence: float | None = None
    valid_from: date | None = None
    available_at: datetime | None = None
    details: dict[str, Any] = Field(default_factory=dict)


def _text(sql: str) -> Any:
    from sqlalchemy import text

    return text(sql)


def _occurred(result: LedgerResult, fingerprint: str) -> date | None:
    for event in result.events:
        if fingerprint in event.claim_fingerprints and event.occurred_on is not None:
            return event.occurred_on
    return None


async def stated_links(
    evidence: Sequence[tuple[EvidenceDocument, LedgerResult]],
    *,
    company_for: CompanyFor,
    hidden_keys: set[str],
    settings: Settings,
) -> list[PendingLink]:
    """company -[role]-> procedure for every verified, named subject of a grouped record."""
    grouped: dict[tuple[str, str, str], PendingLink] = {}
    for doc, result in evidence:
        proc = procedure_id(doc)
        if proc is None:
            continue
        for check in result.checks:
            subject = check.draft.subject
            if not check.verified or subject is None or subject.name.startswith(_WITHHELD):
                continue
            key = company_key(subject.name, subject.country, settings)
            if key in hidden_keys:
                continue
            company = str(await company_for(key, subject.name, subject.country))
            ident = (company, subject.role, proc)
            prior = grouped.get(ident)
            if prior is None:
                grouped[ident] = PendingLink(
                    src_kind=NodeKind.COMPANY,
                    src_id=company,
                    dst_kind=NodeKind.PROCEDURE,
                    dst_id=proc,
                    relation=subject.role,
                    derivation=LinkDerivation.STATED,
                    claim_fingerprints=[check.fingerprint],
                    valid_from=_occurred(result, check.fingerprint),
                    available_at=doc.available_at,
                )
            elif check.fingerprint not in prior.claim_fingerprints:
                prior.claim_fingerprints.append(check.fingerprint)
    return list(grouped.values())


async def bidder_links(
    run: RadarRun,
    evidence: Sequence[tuple[EvidenceDocument, LedgerResult]],
    *,
    company_for: CompanyFor,
    settings: Settings,
) -> list[PendingLink]:
    """procedure -[likely_bidder]-> company for each listed likely bidder with verified wins."""
    docs = {doc.id: doc for doc, _ in evidence}
    winner_lines: dict[str, list[str]] = {}  # company key -> verified winner claim fingerprints
    for _, result in evidence:
        for check in result.checks:
            subject = check.draft.subject
            if (
                check.verified
                and subject is not None
                and check.draft.source_quote.startswith(_WINNER_PREFIX)
            ):
                key = company_key(subject.name, subject.country, settings)
                winner_lines.setdefault(key, []).append(check.fingerprint)
    links: list[PendingLink] = []
    for entry in run.entries:
        procs = sorted(
            {
                p
                for c in entry.candidate.claims
                if c.document_id in docs and (p := procedure_id(docs[c.document_id])) is not None
            }
        )
        for bidder in entry.likely_bidders:
            if bidder.name.startswith(_WITHHELD):
                continue
            key = company_key(bidder.name, bidder.country, settings)
            proof = sorted(set(winner_lines.get(key, [])))
            if not proof:
                continue  # no verified win in this run's evidence: no line (rule #2)
            company = str(await company_for(key, bidder.name, bidder.country))
            confidence = round(min(0.9, bidder.wins / (bidder.wins + 1)), 2)
            for proc in procs:
                links.append(
                    PendingLink(
                        src_kind=NodeKind.PROCEDURE,
                        src_id=proc,
                        dst_kind=NodeKind.COMPANY,
                        dst_id=company,
                        relation="likely_bidder",
                        derivation=LinkDerivation.INFERRED,
                        claim_fingerprints=proof,
                        confidence=confidence,
                        valid_from=run.as_of.date(),
                        available_at=run.as_of,
                        details={
                            "wins": bidder.wins,
                            "last_won": bidder.last_won,
                            "basis": "won similar awards in this country within "
                            f"{settings.radar_bidder_lookback_days} days; "
                            "confidence = wins / (wins + 1), capped at 0.9",
                        },
                    )
                )
    return links


async def save_links(
    session: Any,
    links: Sequence[PendingLink],
    claim_ids: dict[str, UUID],
    *,
    workspace_id: UUID | None = None,
) -> int:
    """Write lines idempotently; more claims for an existing line are merged into it. Every
    claim must be in `verified_claims`, or nothing is written."""
    if not links:
        return 0
    wanted = {str(claim_ids[fp]) for link in links for fp in link.claim_fingerprints}
    found = await session.execute(
        _text("SELECT id FROM verified_claims WHERE id = ANY(CAST(:ids AS uuid[]))"),
        {"ids": sorted(wanted)},
    )
    good = {str(r[0]) for r in found.all()}
    if wanted - good:
        raise ValueError(f"links cite unverified claims: {sorted(wanted - good)}")
    insert = _text(
        "INSERT INTO links (workspace_id, src_kind, src_id, dst_kind, dst_id, relation, "
        "derivation, claim_ids, confidence, valid_from, available_at, details, fingerprint) "
        "VALUES (:workspace_id, :src_kind, :src_id, :dst_kind, :dst_id, :relation, :derivation, "
        "CAST(:claim_ids AS uuid[]), :confidence, :valid_from, :available_at, "
        "CAST(:details AS jsonb), :fingerprint) "
        "ON CONFLICT (fingerprint) DO UPDATE SET "
        "claim_ids = (SELECT array_agg(DISTINCT x ORDER BY x) "
        "FROM unnest(links.claim_ids || EXCLUDED.claim_ids) AS x), "
        "confidence = EXCLUDED.confidence, details = EXCLUDED.details, "
        "valid_from = LEAST(links.valid_from, EXCLUDED.valid_from), "
        "available_at = LEAST(links.available_at, EXCLUDED.available_at)"
    )
    for link in links:
        src = (link.src_kind, link.src_id)
        dst = (link.dst_kind, link.dst_id)
        await session.execute(
            insert,
            {
                "workspace_id": workspace_id,
                "src_kind": link.src_kind.value,
                "src_id": link.src_id,
                "dst_kind": link.dst_kind.value,
                "dst_id": link.dst_id,
                "relation": link.relation,
                "derivation": link.derivation.value,
                "claim_ids": sorted({str(claim_ids[fp]) for fp in link.claim_fingerprints}),
                "confidence": link.confidence,
                "valid_from": link.valid_from,
                "available_at": link.available_at,
                "details": json.dumps(link.details, default=str, sort_keys=True),
                "fingerprint": link_fingerprint(
                    src, dst, link.relation, link.derivation, workspace_id
                ),
            },
        )
    return len({(link.src_id, link.dst_id, link.relation, link.derivation) for link in links})


# --- reading the web -----------------------------------------------------------------------


class GraphNode(NorthvaineModel):
    kind: NodeKind
    id: str
    label: str
    country: str | None = None


class GraphEvidence(NorthvaineModel):
    quote: str
    url: str


class GraphEdge(NorthvaineModel):
    src: str  # "<kind>:<id>"
    dst: str
    relation: str
    derivation: LinkDerivation
    confidence: float | None
    valid_from: date | None
    evidence: list[GraphEvidence]


class GraphView(NorthvaineModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]


def node_ref(kind: NodeKind | str, ident: str) -> str:
    return f"{NodeKind(kind).value}:{ident}"


async def neighbourhood(
    session: Any,
    kind: NodeKind,
    ident: str,
    *,
    depth: int = 2,
    limit: int = 200,
    as_of: datetime | None = None,
) -> GraphView:
    """Every line within `depth` steps of a node, either direction, each with its quotes.
    `as_of` hides lines not yet knowable then (replay)."""
    rows = await session.execute(
        _text(
            "WITH RECURSIVE walk(kind, id, depth) AS ("
            " SELECT CAST(:kind AS text), CAST(:id AS text), 0"
            " UNION"
            " SELECT CASE WHEN l.src_kind = w.kind AND l.src_id = w.id THEN l.dst_kind"
            "             ELSE l.src_kind END,"
            "        CASE WHEN l.src_kind = w.kind AND l.src_id = w.id THEN l.dst_id"
            "             ELSE l.src_id END,"
            "        w.depth + 1"
            " FROM walk w JOIN links l ON (l.src_kind = w.kind AND l.src_id = w.id)"
            "   OR (l.dst_kind = w.kind AND l.dst_id = w.id)"
            " WHERE w.depth < :depth"
            "   AND (CAST(:as_of AS timestamptz) IS NULL OR l.available_at IS NULL"
            "        OR l.available_at <= CAST(:as_of AS timestamptz))"
            ") "
            "SELECT DISTINCT l.id, l.src_kind, l.src_id, l.dst_kind, l.dst_id, l.relation, "
            "l.derivation, l.confidence, l.valid_from, l.claim_ids "
            "FROM links l JOIN walk w ON (l.src_kind = w.kind AND l.src_id = w.id) "
            "OR (l.dst_kind = w.kind AND l.dst_id = w.id) "
            "WHERE (CAST(:as_of AS timestamptz) IS NULL OR l.available_at IS NULL "
            "OR l.available_at <= CAST(:as_of AS timestamptz)) "
            "ORDER BY l.id LIMIT :limit"
        ),
        {"kind": kind.value, "id": ident, "depth": depth, "as_of": as_of, "limit": limit},
    )
    links = rows.all()
    claim_set = sorted({str(c) for row in links for c in row.claim_ids})
    quotes: dict[str, GraphEvidence] = {}
    if claim_set:
        found = await session.execute(
            _text(
                "SELECT v.id, v.source_quote, d.url FROM verified_claims v "
                "JOIN documents d ON d.id = v.document_id WHERE v.id = ANY(CAST(:ids AS uuid[]))"
            ),
            {"ids": claim_set},
        )
        quotes = {str(r.id): GraphEvidence(quote=r.source_quote, url=r.url) for r in found.all()}

    refs: set[tuple[str, str]] = {(kind.value, ident)}
    edges: list[GraphEdge] = []
    for row in links:
        refs.add((row.src_kind, row.src_id))
        refs.add((row.dst_kind, row.dst_id))
        edges.append(
            GraphEdge(
                src=node_ref(row.src_kind, row.src_id),
                dst=node_ref(row.dst_kind, row.dst_id),
                relation=row.relation,
                derivation=LinkDerivation(row.derivation),
                confidence=row.confidence,
                valid_from=row.valid_from,
                evidence=[quotes[str(c)] for c in row.claim_ids if str(c) in quotes],
            )
        )
    nodes = await _labels(session, refs)
    return GraphView(nodes=nodes, edges=edges)


async def _labels(session: Any, refs: set[tuple[str, str]]) -> list[GraphNode]:
    """A readable label per node: a company's name, an event's description, a procedure's
    latest document title."""
    companies = sorted(i for k, i in refs if k == NodeKind.COMPANY.value)
    events = sorted(i for k, i in refs if k == NodeKind.EVENT.value)
    procedures = sorted(i for k, i in refs if k == NodeKind.PROCEDURE.value)
    names: dict[tuple[str, str], tuple[str, str | None]] = {}
    if companies:
        found = await session.execute(
            _text(
                "SELECT CAST(id AS text) AS id, name, country FROM companies "
                "WHERE CAST(id AS text) = ANY(CAST(:ids AS text[]))"
            ),
            {"ids": companies},
        )
        for r in found.all():
            names[(NodeKind.COMPANY.value, r.id)] = (r.name, r.country)
    if events:
        found = await session.execute(
            _text(
                "SELECT CAST(id AS text) AS id, coalesce(description, event_type) AS label "
                "FROM events WHERE CAST(id AS text) = ANY(CAST(:ids AS text[]))"
            ),
            {"ids": events},
        )
        for r in found.all():
            names[(NodeKind.EVENT.value, r.id)] = (r.label, None)
    if procedures:
        found = await session.execute(
            _text(
                "SELECT DISTINCT ON (s.name, d.group_key) s.name || ':' || d.group_key AS id, "
                "coalesce(d.title, d.url) AS label FROM documents d "
                "JOIN sources s ON s.id = d.source_id "
                "WHERE s.name || ':' || d.group_key = ANY(CAST(:ids AS text[])) "
                "ORDER BY s.name, d.group_key, d.available_at DESC NULLS LAST"
            ),
            {"ids": procedures},
        )
        for r in found.all():
            names[(NodeKind.PROCEDURE.value, r.id)] = (r.label, None)
    return [
        GraphNode(
            kind=NodeKind(k),
            id=i,
            label=names.get((k, i), (i, None))[0],
            country=names.get((k, i), (i, None))[1],
        )
        for k, i in sorted(refs)
    ]
