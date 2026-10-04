"""The evidence pipeline: document -> claims -> verified claims -> events (T4.5; helpers T4.0).

Never reads or writes `claims` directly: storage goes through `core/ledger.py` (CLAUDE.md #2).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from datetime import date, datetime
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from northvaine.brain.budget import RunContext
from northvaine.core.models import (
    ClaimCheck,
    DocumentRow,
    EventConceptRow,
    EventDraft,
    EvidenceDocument,
    LedgerResult,
    SubjectMention,
)
from northvaine.core.settings import Settings
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


def ground_event(draft: EventDraft, checks: list[ClaimCheck]) -> EventDraft | None:
    """Keep a date, subject, country or string slot only if it appears in a verified quote of
    this event's claims; None when no verified claim remains (D50)."""
    raise NotImplementedError("T4.5")


def describe_event(event_type: str, subject: SubjectMention | None, statements: list[str]) -> str:
    """The event description, composed by code from verified statements (never LLM text)."""
    raise NotImplementedError("T4.5")


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
    raise NotImplementedError("T4.5")


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
    raise NotImplementedError("T4.5")
