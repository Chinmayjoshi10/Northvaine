"""Buyer-or-seller gate (T5.4, D62-D63): code rejects the unidentified, one mid-tier call per
candidate decides the rest, through `northvaine/brain/llm.py` (rule #8).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from northvaine.brain.budget import RunContext
from northvaine.core.models import NorthvaineModel
from northvaine.core.settings import Settings
from northvaine.radar.models import Candidate, ClientSpec, GateDecision

__all__ = ["GateOutput", "gate_candidate", "numbers_grounded"]


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


def numbers_grounded(text: str, quotes: list[str]) -> bool:
    """True when every number in `text` appears in one of `quotes` (D63)."""
    raise NotImplementedError("T5.4")


async def gate_candidate(
    candidate: Candidate,
    spec: ClientSpec,
    *,
    run: RunContext,
    session: Any = None,
    settings: Settings | None = None,
) -> GateDecision:
    """Decide buyer or rejection for one candidate, before any investigation (rule #3)."""
    raise NotImplementedError("T5.4")
