"""The evidence pipeline: document -> claims -> verified claims -> events (T4.5; helpers T4.0).

Never reads or writes `claims` directly: storage goes through `core/ledger.py` (CLAUDE.md #2).
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Sequence
from datetime import date, datetime
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from northvaine.brain.budget import RunContext
from northvaine.core import ledger as store
from northvaine.core.models import (
    ClaimCheck,
    ClusterCandidate,
    DocumentRow,
    EventConceptRow,
    EventDraft,
    EvidenceDocument,
    EvidenceKind,
    LedgerResult,
    NewEvent,
    PendingEvent,
    QuoteMode,
    SubjectMention,
)
from northvaine.core.settings import Settings, get_settings
from northvaine.core.standards import iso2_to_iso3, iso2_to_name
from northvaine.radar.concepts import assign_cluster, assign_concept
from northvaine.radar.extract import document_event_types, extract
from northvaine.radar.quote_check import normalize_text, quote_contains
from northvaine.radar.structured import structured_evidence
from northvaine.radar.verify import is_evidence_document, verify_claims
from northvaine.sensors.base import SensorDocument

__all__ = [
    "build_evidence",
    "describe_event",
    "event_fingerprint",
    "evidence_document_from_row",
    "evidence_document_from_sensor",
    "ground_event",
    "process_document",
]


def evidence_document_from_row(row: DocumentRow, source_name: str) -> EvidenceDocument:
    """A stored `documents` row as an evidence document; `source_name` is the sources.name."""
    return EvidenceDocument(
        id=row.id,
        source_name=source_name,
        url=row.url,
        title=row.title,
        text=row.text,
        available_at=row.available_at,
        workspace_id=row.workspace_id,
        group_key=row.group_key,
        meta=dict(row.meta),
    )


def evidence_document_from_sensor(
    doc: SensorDocument, *, document_id: UUID | None = None
) -> EvidenceDocument:
    """A sensor snapshot as an evidence document. The id defaults to a deterministic
    `uuid5(NAMESPACE_URL, content_hash)`, so offline runs and replays agree."""
    return EvidenceDocument(
        id=document_id if document_id is not None else uuid5(NAMESPACE_URL, doc.content_hash),
        source_name=doc.source,
        url=doc.url,
        title=doc.title,
        text=doc.text,
        available_at=doc.available_at,
        workspace_id=None,
        group_key=doc.group_key,
        meta=dict(doc.meta),
    )


def event_fingerprint(
    event_type: str,
    claim_fingerprints: Sequence[str],
    occurred_on: date | None,
    subject_key: str | None,
) -> str:
    """sha256 over (event_type, sorted claim fingerprints, occurred_on, subject key).

    The order of the claim fingerprints does not matter; any other change changes the result.
    """
    payload = json.dumps(
        [
            event_type,
            sorted(claim_fingerprints),
            occurred_on.isoformat() if occurred_on is not None else None,
            subject_key,
        ],
        ensure_ascii=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _word_in(quote: str, word: str) -> bool:
    """`word` as a whole token of `quote` (case-insensitive); a bare substring would let the
    code 'DE' match any word that contains those letters."""
    return re.search(rf"(?<![A-Za-z0-9]){re.escape(word)}(?![A-Za-z0-9])", quote, re.I) is not None


def _country_grounded(code: str, quotes: list[str]) -> bool:
    """The ISO2 code or its ISO3 code as a whole token, or the country name, is in a quote."""
    try:
        name = iso2_to_name(code)
        iso3 = iso2_to_iso3(code)
    except KeyError:
        return False
    for quote in quotes:
        norm = normalize_text(quote)
        if _word_in(norm, code) or _word_in(norm, iso3) or quote_contains(quote, name):
            return True
    return False


def _subject_key(subject: SubjectMention | None) -> str | None:
    if subject is None:
        return None
    return normalize_text(subject.name).casefold().strip() or None


def ground_event(draft: EventDraft, checks: list[ClaimCheck]) -> EventDraft | None:
    """Keep a date, subject, country or string slot only if it appears in a verified quote of
    this event's claims; None when no verified claim remains (D50)."""
    kept = [
        i for i in dict.fromkeys(draft.claim_indices) if 0 <= i < len(checks) and checks[i].verified
    ]
    if not kept:
        return None
    quotes = [checks[i].draft.source_quote for i in kept]

    def grounded(fragment: str) -> bool:
        return any(quote_contains(q, fragment) for q in quotes)

    date_ok = bool(draft.date_text) and grounded(draft.date_text or "")
    subject = draft.subject
    if subject is not None:
        if not grounded(subject.name):
            subject = None
        elif subject.country is not None and not _country_grounded(subject.country, quotes):
            subject = subject.model_copy(update={"country": None})
    slots = {
        name: value
        for name, value in draft.slots.items()
        if not isinstance(value, str) or grounded(value)
    }
    return draft.model_copy(
        update={
            "claim_indices": kept,
            "date_text": draft.date_text if date_ok else None,
            "occurred_on": draft.occurred_on if date_ok else None,
            "subject": subject,
            "slots": slots,
        }
    )


def describe_event(event_type: str, subject: SubjectMention | None, statements: list[str]) -> str:
    """The event description, composed by code from verified statements (never LLM text)."""
    head = event_type.replace("_", " ")
    if subject is not None:
        head = f"{head} - {subject.name}"
    unique = list(dict.fromkeys(s.strip() for s in statements if s.strip()))
    return " ".join([f"{head}.", *unique])


async def build_evidence(
    doc: EvidenceDocument,
    concepts: list[EventConceptRow],
    recent_events: list[Any],
    *,
    run: RunContext,
    session: Any = None,
    settings: Settings | None = None,
) -> LedgerResult:
    """Eligibility, extraction, verification, grounding, concepts and clusters; no storage."""
    settings = settings or get_settings()
    eligibility = is_evidence_document(doc, settings)
    if eligibility.kind == EvidenceKind.LEAD:
        return LedgerResult(document_id=doc.id, eligibility=eligibility)

    llm_calls = 0
    structured = eligibility.kind == EvidenceKind.STRUCTURED
    if structured:
        drafted = structured_evidence(doc)
        if drafted is None:
            return LedgerResult(document_id=doc.id, eligibility=eligibility)
        claims, event_drafts = drafted
        checks = await verify_claims(
            doc,
            claims,
            run=run,
            mode=QuoteMode.STRUCTURED,
            support=False,
            session=session,
            settings=settings,
        )
    else:
        if document_event_types(concepts, settings):
            llm_calls += 1  # the extract call
        claims, event_drafts = await extract(
            doc, concepts, run=run, session=session, settings=settings
        )
        checks = await verify_claims(
            doc,
            claims,
            run=run,
            mode=QuoteMode.EXTRACTED,
            support=True,
            session=session,
            settings=settings,
        )
        if any(c.quote_offset is not None for c in checks):
            llm_calls += 1  # the batched support call

    known_types = {c.label for c in concepts if c.level == 0}
    candidates: list[ClusterCandidate] = list(recent_events)
    events: list[PendingEvent] = []
    for draft in event_drafts:
        if draft.event_type not in known_types:
            continue
        grounded = ground_event(draft, checks)
        if grounded is None:
            continue
        statements = [checks[i].draft.statement for i in grounded.claim_indices]
        description = describe_event(grounded.event_type, grounded.subject, statements)
        embedding: list[float] | None = None
        if not structured:
            # Imported here: brain.llm pulls in the SDK (httpx), which importing radar must not do.
            from northvaine.brain.llm import embed

            embedded = await embed(
                text=description,
                purpose="event_embed",
                run=run,
                workspace_id=doc.workspace_id,
                session=session,
            )
            embedding = embedded.value
            llm_calls += 1
        concept = assign_concept(grounded, embedding, concepts, settings=settings)
        subject_key = _subject_key(grounded.subject)
        group_key = grounded.group_key
        candidate = ClusterCandidate(
            cluster_id=uuid4(),
            event_type=grounded.event_type,
            occurred_on=grounded.occurred_on,
            subject_key=subject_key,
            group_key=group_key,
            embedding=embedding,
            available_at=doc.available_at,
        )
        cluster_id = assign_cluster(candidate, candidates, settings=settings)
        candidates.append(candidate.model_copy(update={"cluster_id": cluster_id}))
        slots = dict(grounded.slots)
        if subject_key is not None:
            slots["subject_key"] = subject_key
        if group_key is not None:
            slots["group_key"] = group_key
        fingerprints = [checks[i].fingerprint for i in grounded.claim_indices]
        events.append(
            PendingEvent(
                event_type=grounded.event_type,
                claim_fingerprints=fingerprints,
                occurred_on=grounded.occurred_on,
                available_at=doc.available_at,
                subject=grounded.subject,
                description=description,
                embedding=embedding,
                concept=concept,
                cluster_id=cluster_id,
                slots=slots,
                details={"document_id": str(doc.id)},
                fingerprint=event_fingerprint(
                    grounded.event_type, fingerprints, grounded.occurred_on, subject_key
                ),
            )
        )
    return LedgerResult(
        document_id=doc.id,
        eligibility=eligibility,
        checks=checks,
        events=events,
        llm_calls=llm_calls,
    )


async def process_document(
    session: Any,
    doc: EvidenceDocument,
    *,
    run: RunContext,
    as_of: datetime | None = None,
    settings: Settings | None = None,
) -> LedgerResult:
    """build_evidence, then save claims, new concepts and events (idempotent). Refuses a
    document with `workspace_id` set (private documents are parked)."""
    if doc.workspace_id is not None:
        raise ValueError("private documents are parked: process_document needs a public document")
    settings = settings or get_settings()

    concepts = await store.load_concepts(session)
    recent: list[ClusterCandidate] = []
    if is_evidence_document(doc, settings).kind != EvidenceKind.LEAD:
        cutoff = as_of or doc.available_at
        for label in sorted({c.label for c in concepts if c.level == 0}):
            recent.extend(
                await store.events_for_clustering(
                    session,
                    event_type=label,
                    occurred_from=None,
                    occurred_to=None,
                    as_of=cutoff,
                )
            )
    result = await build_evidence(
        doc, concepts, recent, run=run, session=session, settings=settings
    )
    if not result.checks:
        return result

    claim_ids = await store.save_claims(session, result.checks)
    new_events: list[NewEvent] = []
    for event in result.events:
        concept_id = event.concept.concept_id
        if event.concept.is_new:
            concept_id = await store.ensure_concept(session, event.concept)
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
                details=event.details,
                fingerprint=event.fingerprint,
            )
        )
    await store.save_events(session, new_events)
    return result
