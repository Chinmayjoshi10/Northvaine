"""Code-only evidence from structured official records (T4.3, D46).

No LLM. `source_quote` is one exact rendered line of `documents.text`; the statement is a generic
template over the same field.
"""

from __future__ import annotations

from northvaine.core.models import ClaimDraft, EventDraft, EvidenceDocument

__all__ = ["structured_evidence"]


def structured_evidence(
    doc: EvidenceDocument,
) -> tuple[list[ClaimDraft], list[EventDraft]] | None:
    """Claim and event drafts for a structured record, or None when the record is not understood."""
    raise NotImplementedError("T4.3")
