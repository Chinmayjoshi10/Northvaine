"""Skeptic (T5.4, D62-D63): evidence against a passed candidate, cited, or 'unknown' with open
questions. One mid-tier call through `northvaine/brain/llm.py` (rule #8).
"""

from __future__ import annotations

from typing import Any

from pydantic import Field

from northvaine.brain.budget import RunContext
from northvaine.core.models import NorthvaineModel
from northvaine.core.settings import Settings
from northvaine.radar.models import Candidate, ClientSpec, GateDecision, SkepticFinding

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
    raise NotImplementedError("T5.4")
