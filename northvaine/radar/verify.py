"""Claim verification: eligibility, fingerprints, the code quote check, then one batched LLM
support check over the claims whose quotes passed (T4.2, D45, D47, D49).

`SupportOutput` is the frozen strict-schema reply of the support check. Output models carry no
docstrings and no `Field(description=...)`: Pydantic would emit `description`, a keyword the
strict json_schema path has not been confirmed to honour (PF1). Keep explanations in comments.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel

from northvaine.brain.budget import RunContext
from northvaine.core.models import (
    ClaimCheck,
    ClaimDraft,
    Eligibility,
    EvidenceDocument,
    QuoteMode,
)
from northvaine.core.settings import Settings

__all__ = [
    "SupportOutput",
    "SupportVerdict",
    "claim_fingerprint",
    "is_evidence_document",
    "verify_claims",
]


# index: position of the claim in the batch sent to the model; supported: does the quote say it.
class SupportVerdict(BaseModel):
    index: int
    supported: bool


class SupportOutput(BaseModel):
    verdicts: list[SupportVerdict]


def is_evidence_document(doc: EvidenceDocument, settings: Settings | None = None) -> Eligibility:
    """Apply `settings.evidence_source_rules` (fail closed): structured, full_text or lead."""
    raise NotImplementedError("T4.2")


def claim_fingerprint(document_id: UUID, statement: str, source_quote: str) -> str:
    """sha256 over the document id, the statement and the quote (normalized whitespace)."""
    raise NotImplementedError("T4.2")


async def verify_claims(
    doc: EvidenceDocument,
    drafts: list[ClaimDraft],
    *,
    run: RunContext,
    mode: QuoteMode = QuoteMode.EXTRACTED,
    support: bool = True,
    session: Any = None,
    settings: Settings | None = None,
) -> list[ClaimCheck]:
    """Code quote check first, then (when `support`) one fast-tier call over passing quotes only.

    A missing verdict means unsupported. `mode=structured` refuses any document whose
    eligibility is not `structured` (status `ineligible_document`).
    """
    raise NotImplementedError("T4.2")
