"""Extraction: one fast-tier call per full-text document drafts claims and events (T4.3, D47).

Output models are frozen strict-schema shapes (PF1): no docstrings, no `Field(description=...)`,
no `pattern`/`minLength`/`format`/`const`/`oneOf`. Nullable fields render as `anyOf [X, null]`.
ISO2 and snake_case checks happen in code. `ExtractionOutput.claims` and `.events` carry a
literal `maxItems` of 8, the `extract_max_claims` default; a test asserts they agree.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field

from northvaine.brain.budget import RunContext
from northvaine.brain.fencing import Untrusted
from northvaine.brain.prompts import load_prompt
from northvaine.core.models import (
    SNAKE,
    ClaimDraft,
    ConceptStatus,
    EventConceptRow,
    EventDraft,
    EvidenceDocument,
    ModelTier,
    SubjectMention,
)
from northvaine.core.settings import Settings, get_settings
from northvaine.core.standards import iso2_to_name
from northvaine.sensors.dates import parse_date

__all__ = [
    "ExtractedClaim",
    "ExtractedEvent",
    "ExtractionOutput",
    "SlotValue",
    "document_event_types",
    "extract",
]


# One named slot value; a list of these keeps the schema free of free-form objects.
class SlotValue(BaseModel):
    name: str
    value: str


# source_quote must be copied verbatim from the document; code verifies it afterwards.
class ExtractedClaim(BaseModel):
    statement: str
    source_quote: str
    subject_name: str | None = None
    subject_country: str | None = None
    subject_role: str | None = None


# claim_indices point into ExtractionOutput.claims; event_type is a label from the data-driven
# list in the prompt; date_text is the date as written in the quote, never a computed one.
class ExtractedEvent(BaseModel):
    event_type: str
    claim_indices: list[int]
    subject_name: str | None = None
    date_text: str | None = None
    group_hint: str | None = None
    slots: list[SlotValue]
    concept_label: str | None = None
    concept_hint: str | None = None


class ExtractionOutput(BaseModel):
    claims: list[ExtractedClaim] = Field(max_length=8)
    events: list[ExtractedEvent] = Field(max_length=8)


def document_event_types(
    concepts: list[EventConceptRow], settings: Settings | None = None
) -> list[EventConceptRow]:
    """Level-0 active concepts minus `settings.extract_excluded_event_types`."""
    settings = settings or get_settings()
    excluded = set(settings.extract_excluded_event_types)
    return [
        c
        for c in concepts
        if c.level == 0 and c.status == ConceptStatus.ACTIVE and c.label not in excluded
    ]


_SNAKE = re.compile(SNAKE)
_UNKNOWN_ROLE = "unknown"  # SubjectMention.role is required; used when the model gave none


def _snake_or_none(value: str | None) -> str | None:
    value = (value or "").strip()
    return value if _SNAKE.match(value) else None


def _iso2_or_none(value: str | None) -> str | None:
    code = (value or "").strip().upper()
    if len(code) != 2:
        return None
    try:
        iso2_to_name(code)
    except KeyError:
        return None
    return code


def _subject(
    name: str | None, country: str | None = None, role: str | None = None
) -> SubjectMention | None:
    name = (name or "").strip()
    if not name:
        return None
    return SubjectMention(
        name=name, country=_iso2_or_none(country), role=_snake_or_none(role) or _UNKNOWN_ROLE
    )


def _event_subject(
    name: str | None, indices: list[int], claims: list[ClaimDraft]
) -> SubjectMention | None:
    """The event subject; country and role come from a referenced claim about the same name."""
    name = (name or "").strip()
    if not name:
        return None
    for i in indices:
        known = claims[i].subject
        if known is not None and known.name.casefold() == name.casefold():
            return known
    return _subject(name)


async def extract(
    doc: EvidenceDocument,
    concepts: list[EventConceptRow],
    *,
    run: RunContext,
    session: Any = None,
    settings: Settings | None = None,
) -> tuple[list[ClaimDraft], list[EventDraft]]:
    """One fast-tier `complete_json` call; document text, title and url are all fenced."""
    settings = settings or get_settings()
    allowed = document_event_types(concepts, settings)
    if not allowed:
        return [], []
    labels = {c.label for c in allowed}

    text = doc.text
    note = ""
    if len(text) > settings.extract_max_doc_chars:
        text = text[: settings.extract_max_doc_chars]
        note = (
            f"Note: the document was truncated to its first {settings.extract_max_doc_chars} "
            "characters. Only quote text that appears above."
        )

    # Imported here: brain.llm pulls in the SDK (httpx), which module import must not do.
    from northvaine.brain.llm import complete_json

    result = await complete_json(
        tier=ModelTier.FAST,
        prompt=load_prompt("evidence_extract"),
        variables={
            "doc_title": Untrusted(doc.title or ""),
            "doc_url": Untrusted(doc.url),
            "doc_text": Untrusted(text),
            "truncation_note": note,
            "event_types": "\n".join(f"- {c.label}: {c.description}" for c in allowed),
            "max_claims": str(settings.extract_max_claims),
        },
        output_model=ExtractionOutput,
        purpose="evidence_extract",
        run=run,
        workspace_id=doc.workspace_id,
        session=session,
        max_tokens=settings.extract_max_tokens,
    )
    output = result.value

    claims = [
        ClaimDraft(
            statement=c.statement,
            source_quote=c.source_quote,
            subject=_subject(c.subject_name, c.subject_country, c.subject_role),
            extracted_by=result.model,
        )
        for c in output.claims[: settings.extract_max_claims]
    ]

    events: list[EventDraft] = []
    for e in output.events:
        if e.event_type not in labels:
            continue
        indices = [i for i in dict.fromkeys(e.claim_indices) if 0 <= i < len(claims)]
        if not indices:
            continue
        slots = {s.name: s.value for s in e.slots if _SNAKE.match(s.name) and s.value.strip()}
        events.append(
            EventDraft(
                event_type=e.event_type,
                claim_indices=indices,
                subject=_event_subject(e.subject_name, indices, claims),
                date_text=e.date_text,
                occurred_on=parse_date(e.date_text),
                group_key=(e.group_hint or "").strip() or None,
                slots=slots,
                concept_label=_snake_or_none(e.concept_label),
                concept_hint=(e.concept_hint or "").strip() or None,
            )
        )
    return claims, events
