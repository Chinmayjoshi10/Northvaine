"""Extraction: one fast-tier call per full-text document drafts claims and events (T4.3, D47).

Output models are frozen strict-schema shapes (PF1): no docstrings, no `Field(description=...)`,
no `pattern`/`minLength`/`format`/`const`/`oneOf`. Nullable fields render as `anyOf [X, null]`.
ISO2 and snake_case checks happen in code. `ExtractionOutput.claims` and `.events` carry a
literal `maxItems` of 8, the `extract_max_claims` default; a test asserts they agree.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from northvaine.brain.budget import RunContext
from northvaine.core.models import ClaimDraft, EventConceptRow, EventDraft, EvidenceDocument
from northvaine.core.settings import Settings

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
    raise NotImplementedError("T4.3")


async def extract(
    doc: EvidenceDocument,
    concepts: list[EventConceptRow],
    *,
    run: RunContext,
    session: Any = None,
    settings: Settings | None = None,
) -> tuple[list[ClaimDraft], list[EventDraft]]:
    """One fast-tier `complete_json` call; document text, title and url are all fenced."""
    raise NotImplementedError("T4.3")
