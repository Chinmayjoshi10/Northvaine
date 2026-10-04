"""Buyer-or-seller gate (T5.4, D62-D63): code rejects the unidentified, one mid-tier call per
candidate decides the rest, through `northvaine/brain/llm.py` (rule #8).
"""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import Field

from northvaine.brain.budget import RunContext
from northvaine.brain.fencing import Untrusted
from northvaine.brain.prompts import load_prompt
from northvaine.core.models import ModelTier, NorthvaineModel
from northvaine.core.settings import Settings, get_settings
from northvaine.radar.models import Candidate, CandidateClaim, ClientSpec, GateDecision, RejectedAs

__all__ = ["GateOutput", "claim_lines", "gate_candidate", "numbers_grounded"]


# Strict-schema shape (PF1): no docstring, no descriptions, every field required.
class GateOutput(NorthvaineModel):
    verdict: Literal[
        "buyer", "competitor", "reseller", "publisher", "not_a_buyer", "not_an_organisation"
    ]
    direct_buyer: bool | None
    reason: str
    buyer_reason: str | None
    demand_reason: str | None
    suggested_action: str | None
    cited_refs: list[str] = Field(max_length=8)


_NUMBER = re.compile(r"\d(?:[\d.,]*\d)?")
_THOUSANDS = re.compile(r"^\d{1,3}(?:[.,]\d{3})+$")

NOT_AN_ORGANISATION_REASON = "subject is not an organisation (name withheld)"
UNGROUNDED_REASON = "reason withheld: it contained a figure no verified quote supports"


def _number_forms(token: str) -> set[str]:
    """Spellings of one number that count as the same: ',' or '.' decimals, thousands marks."""
    forms = {token.replace(",", ".")}
    if _THOUSANDS.match(token):
        forms.add(re.sub(r"[.,]", "", token))
    return forms


def numbers_grounded(text: str, quotes: list[str]) -> bool:
    """True when every number in `text` appears in one of `quotes` (D63)."""
    known: set[str] = set()
    for quote in quotes:
        for token in _NUMBER.findall(quote):
            known |= _number_forms(token)
    return all(_number_forms(t) & known for t in _NUMBER.findall(text))


def claim_lines(claims: list[CandidateClaim]) -> str:
    """One `ref: statement / "quote" (source)` line per claim, for the fenced prompt block."""
    return "\n".join(
        f'{c.ref}: {c.statement} / "{c.source_quote}" ({c.source_name})' for c in claims
    )


def _guard(text: str | None, quotes: list[str]) -> str | None:
    text = (text or "").strip()
    return text if text and numbers_grounded(text, quotes) else None


def _reject(
    rejected_as: RejectedAs,
    reason: str,
    by: Literal["code", "llm"],
    cited_refs: list[str] | None = None,
) -> GateDecision:
    return GateDecision(
        passed=False,
        rejected_as=rejected_as,
        by=by,
        reason=reason,
        direct_buyer=None,
        buyer_reason=None,
        demand_reason=None,
        suggested_action=None,
        cited_refs=cited_refs or [],
    )


async def gate_candidate(
    candidate: Candidate,
    spec: ClientSpec,
    *,
    run: RunContext,
    session: Any = None,
    settings: Settings | None = None,
) -> GateDecision:
    """Decide buyer or rejection for one candidate, before any investigation (rule #3)."""
    settings = settings or get_settings()
    if not candidate.claims:
        return _reject(
            RejectedAs.INSUFFICIENT_EVIDENCE, "no verified claim backs this candidate", "code"
        )

    # Imported here: brain.llm pulls in the SDK (httpx), which module import must not do.
    from northvaine.brain.llm import complete_json

    result = await complete_json(
        tier=ModelTier.MID,
        prompt=load_prompt("radar_gate"),
        variables={
            "offer": spec.offer,
            "markets": ", ".join(spec.markets),
            "candidate_name": Untrusted(candidate.name),
            "candidate_roles": Untrusted(", ".join(candidate.roles)),
            "claims": Untrusted(claim_lines(candidate.claims)),
        },
        output_model=GateOutput,
        purpose="radar_gate",
        run=run,
        workspace_id=run.workspace_id,
        session=session,
        max_tokens=settings.gate_max_tokens,
    )
    out = result.value

    by_ref = {c.ref: c for c in candidate.claims}
    refs = [r for r in dict.fromkeys(out.cited_refs) if r in by_ref]
    quotes = [by_ref[r].source_quote for r in refs]
    reason = out.reason.strip()

    if out.verdict == "not_an_organisation":
        return _reject(RejectedAs.NOT_AN_ORGANISATION, NOT_AN_ORGANISATION_REASON, "llm")
    if out.verdict != "buyer":
        # A rejection's reason may lean on any claim, so it is checked against all of them.
        if not reason or not numbers_grounded(reason, [c.source_quote for c in candidate.claims]):
            reason = UNGROUNDED_REASON
        return _reject(RejectedAs(out.verdict), reason, "llm", refs)
    if not refs:
        return _reject(
            RejectedAs.INSUFFICIENT_EVIDENCE, "the buyer verdict cites no verified claim", "llm"
        )

    if not reason or not numbers_grounded(reason, quotes):
        reason = UNGROUNDED_REASON
    return GateDecision(
        passed=True,
        rejected_as=None,
        by="llm",
        reason=reason,
        direct_buyer=out.direct_buyer,
        buyer_reason=_guard(out.buyer_reason, quotes),
        demand_reason=_guard(out.demand_reason, quotes),
        suggested_action=_guard(out.suggested_action, quotes),
        cited_refs=refs,
    )
