"""Claim verification: eligibility, fingerprints, the code quote check, then one batched LLM
support check over the claims whose quotes passed (T4.2, D45, D47, D49).

`SupportOutput` is the frozen strict-schema reply of the support check. Output models carry no
docstrings and no `Field(description=...)`: Pydantic would emit `description`, a keyword the
strict json_schema path has not been confirmed to honour (PF1). Keep explanations in comments.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any
from uuid import UUID

from pydantic import BaseModel

from northvaine.brain.budget import RunContext
from northvaine.brain.fencing import Untrusted
from northvaine.brain.prompts import load_prompt
from northvaine.core.models import (
    ClaimCheck,
    ClaimDraft,
    ClaimStatus,
    Eligibility,
    EvidenceDocument,
    EvidenceKind,
    ModelTier,
    QuoteMode,
)
from northvaine.core.settings import Settings, get_settings
from northvaine.radar.quote_check import find_quote, normalize_text

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


def _lead(reason: str) -> Eligibility:
    return Eligibility(kind=EvidenceKind.LEAD, reason=reason)


def is_evidence_document(doc: EvidenceDocument, settings: Settings | None = None) -> Eligibility:
    """Apply `settings.evidence_source_rules` (fail closed): structured, full_text or lead."""
    settings = settings or get_settings()
    rule = settings.evidence_source_rules.get(doc.source_name)
    if rule is None:
        return _lead(f"source {doc.source_name!r} has no evidence rule")
    if rule == "structured":
        ver = doc.meta.get("schema_ver")
        if type(ver) is int and ver == 1:
            return Eligibility(kind=EvidenceKind.STRUCTURED)
        return _lead("structured source without a known schema_ver")
    if rule == "full_text":
        return Eligibility(kind=EvidenceKind.FULL_TEXT)
    if rule == "raw_only":
        kind = doc.meta.get("text_kind")
        if kind == "raw":
            return Eligibility(kind=EvidenceKind.FULL_TEXT)
        return _lead(f"text_kind {kind!r} is not raw page text")
    return _lead(f"unknown evidence rule {rule!r}")


def claim_fingerprint(document_id: UUID, statement: str, source_quote: str) -> str:
    """sha256 over the document id, the statement (normalized) and the quote."""
    payload = json.dumps(
        [str(document_id), normalize_text(statement), source_quote], ensure_ascii=True
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _check(
    doc: EvidenceDocument,
    draft: ClaimDraft,
    status: ClaimStatus,
    *,
    offset: int | None = None,
    verified_by: str | None = None,
) -> ClaimCheck:
    return ClaimCheck(
        document_id=doc.id,
        draft=draft,
        status=status,
        quote_offset=offset,
        verified_by=verified_by,
        fingerprint=claim_fingerprint(doc.id, draft.statement, draft.source_quote),
    )


def _claims_block(drafts: list[ClaimDraft]) -> str:
    # One JSON object per line: a newline or quote inside a statement cannot forge another entry.
    return "\n".join(
        json.dumps(
            {"index": i, "statement": d.statement, "quote": d.source_quote}, ensure_ascii=True
        )
        for i, d in enumerate(drafts)
    )


async def _support_verdicts(
    doc: EvidenceDocument,
    drafts: list[ClaimDraft],
    *,
    run: RunContext,
    session: Any,
    settings: Settings,
) -> dict[int, bool]:
    """Index -> supported. A duplicated or out-of-range index is dropped (reads as unsupported)."""
    # Imported here: brain.llm pulls in the SDK (and httpx), which importing radar must not do.
    from northvaine.brain.llm import complete_json

    result = await complete_json(
        tier=ModelTier.FAST,
        prompt=load_prompt("claim_support"),
        variables={"claims": Untrusted(_claims_block(drafts))},
        output_model=SupportOutput,
        purpose="claim_support",
        run=run,
        workspace_id=doc.workspace_id,
        session=session,
        max_tokens=settings.support_max_tokens,
    )
    seen: dict[int, bool] = {}
    duplicated: set[int] = set()
    for verdict in result.value.verdicts:
        if verdict.index in seen:
            duplicated.add(verdict.index)
        seen[verdict.index] = verdict.supported
    return {i: ok for i, ok in seen.items() if i not in duplicated and 0 <= i < len(drafts)}


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

    A missing verdict means unsupported. `mode=structured` raises ValueError for a document that
    is not `structured`. Results keep the order of `drafts`.
    """
    settings = settings or get_settings()
    eligibility = is_evidence_document(doc, settings)
    if eligibility.kind == EvidenceKind.LEAD:
        return [_check(doc, d, ClaimStatus.INELIGIBLE_DOCUMENT) for d in drafts]
    if mode == QuoteMode.STRUCTURED and eligibility.kind != EvidenceKind.STRUCTURED:
        raise ValueError(
            f"mode=structured needs a structured document; {doc.source_name!r} is "
            f"{eligibility.kind.value}"
        )

    checks: list[ClaimCheck | None] = [None] * len(drafts)
    passing: list[tuple[int, int]] = []  # (position in drafts, quote offset)
    for i, draft in enumerate(drafts):
        match = find_quote(doc.text, draft.source_quote, mode=mode, settings=settings)
        if match.found and match.offset is not None:
            passing.append((i, match.offset))
        else:
            checks[i] = _check(doc, draft, match.reason or ClaimStatus.QUOTE_NOT_FOUND)

    verdicts: dict[int, bool] = {}
    if support and passing:
        verdicts = await _support_verdicts(
            doc, [drafts[i] for i, _ in passing], run=run, session=session, settings=settings
        )
    for batch_index, (i, offset) in enumerate(passing):
        if not support:
            checks[i] = _check(
                doc, drafts[i], ClaimStatus.VERIFIED, offset=offset, verified_by="code"
            )
        elif verdicts.get(batch_index) is True:
            checks[i] = _check(
                doc, drafts[i], ClaimStatus.VERIFIED, offset=offset, verified_by="code+llm"
            )
        else:
            checks[i] = _check(doc, drafts[i], ClaimStatus.UNSUPPORTED, offset=offset)
    return [c for c in checks if c is not None]
