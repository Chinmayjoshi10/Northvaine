"""Skeptic (T5.4, D62-D63): evidence against a passed candidate, cited, or 'unknown' with open
questions. One mid-tier call through `northvaine/brain/llm.py` (rule #8).
"""

from __future__ import annotations

from typing import Any

from pydantic import Field

from northvaine.brain.budget import RunContext
from northvaine.brain.fencing import Untrusted
from northvaine.brain.prompts import load_prompt
from northvaine.core.models import ModelTier, NorthvaineModel
from northvaine.core.settings import Settings, get_settings
from northvaine.radar.gate import claim_lines, numbers_grounded, ref_of
from northvaine.radar.models import (
    AgainstPoint,
    Candidate,
    ClientSpec,
    GateDecision,
    SkepticFinding,
)

__all__ = ["SkepticItem", "SkepticOutput", "skeptic"]


# Strict-schema shapes (PF1): no docstrings, no descriptions, every field required.
class SkepticItem(NorthvaineModel):
    claim_ref: str
    why: str


class SkepticOutput(NorthvaineModel):
    against: list[SkepticItem] = Field(max_length=4)
    open_questions: list[str] = Field(max_length=3)


async def skeptic(
    candidate: Candidate,
    gate: GateDecision,
    spec: ClientSpec,
    *,
    run: RunContext,
    session: Any = None,
    settings: Settings | None = None,
) -> SkepticFinding:
    """Find cited evidence against the candidate, or return 'unknown' with open questions."""
    if not gate.passed:
        raise ValueError("skeptic runs only after a passed gate (rule #3: gate first)")
    settings = settings or get_settings()

    # Imported here: brain.llm pulls in the SDK (httpx), which module import must not do.
    from northvaine.brain.llm import complete_json

    result = await complete_json(
        tier=ModelTier.MID,
        prompt=load_prompt("radar_skeptic"),
        variables={
            "offer": spec.offer,
            "candidate_name": Untrusted(candidate.name),
            "claims": Untrusted(claim_lines(candidate.claims)),
            "demand_reason": Untrusted(gate.demand_reason or ""),
        },
        output_model=SkepticOutput,
        purpose="radar_skeptic",
        run=run,
        workspace_id=run.workspace_id,
        session=session,
        max_tokens=settings.skeptic_max_tokens,
    )
    out = result.value

    quotes = {c.ref: c.source_quote for c in candidate.claims}
    against = [
        AgainstPoint(claim_ref=ref, why=item.why.strip())
        for item in out.against
        if (ref := ref_of(item.claim_ref)) in quotes
        and item.why.strip()
        and numbers_grounded(item.why, [quotes[ref]])
    ]
    all_quotes = list(quotes.values())
    questions = [
        q.strip() for q in out.open_questions if q.strip() and numbers_grounded(q, all_quotes)
    ]
    return SkepticFinding(
        stance="against" if against else "unknown", against=against, open_questions=questions
    )
