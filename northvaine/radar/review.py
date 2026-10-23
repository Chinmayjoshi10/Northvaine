"""The senior review: the last check before a lead reaches the owner (D127).

The top opportunities go to the deep model, which reads only the lead's checked claims, the reason
it is shown today and the evidence against it, and answers the founder's question: would this
business call them today? A "no" is held back to the watch list with its reason, never deleted.
Code checks that the answer cites real claims; a reply that cites none is not trusted and the
lead is held back too (when unsure, hold back). Never fails a run.
"""

from __future__ import annotations

import asyncio
from typing import Any

from pydantic import Field

from northvaine.brain.budget import RunContext
from northvaine.brain.errors import BudgetExceeded, LlmInvalidOutput, LlmTimeout, LlmTransportError
from northvaine.brain.fencing import Untrusted
from northvaine.brain.prompts import load_prompt
from northvaine.core.models import ModelTier, NorthvaineModel
from northvaine.core.settings import ConfigError
from northvaine.radar.gate import claim_lines, numbers_grounded, ref_of
from northvaine.radar.models import RankedEntry

__all__ = ["ReviewOutput", "review_top"]

_FAILURES = (LlmInvalidOutput, LlmTimeout, LlmTransportError)


class ReviewOutput(NorthvaineModel):
    reasoning: str = ""
    worthy: bool = False
    cited_refs: list[str] = Field(default_factory=list)
    note: str = ""


async def _review(entry: RankedEntry, spec: Any, *, run: RunContext, session: Any) -> ReviewOutput:
    # Imported here: brain.llm pulls in the SDK (httpx), which module import must not do.
    from northvaine.brain.llm import complete_json

    c = entry.candidate
    against = "; ".join(p.why for p in entry.skeptic.against) or "none found"
    result = await complete_json(
        tier=ModelTier.DEEP,
        prompt=load_prompt("radar_review", version=1),
        variables={
            "offer": spec.offer,
            "buyer_roles": "; ".join(spec.buyer_roles) or "not stated",
            "not_buyers": "; ".join(spec.not_buyers) or "not stated",
            "candidate_name": Untrusted(c.name),
            "claims": Untrusted(claim_lines(c.claims)),
            "why_now": Untrusted(entry.opportunity.why_now if entry.opportunity else ""),
            "against": Untrusted(against),
        },
        output_model=ReviewOutput,
        purpose="radar_review",
        run=run,
        workspace_id=run.workspace_id,
        session=session,
    )
    return result.value


async def review_top(
    entries: list[RankedEntry],
    spec: Any,
    *,
    top: int,
    run: RunContext,
    session: Any = None,
    concurrency: int = 4,
) -> tuple[list[RankedEntry], list[str]]:
    """The top `top` non-watch opportunities reviewed (several at a time). A lead held back moves
    to the watch list (its rank is kept; the edition skips it) with the reviewer's note; a lead
    passed carries the note as its first rank reason."""
    out = list(entries)
    picks = [
        i for i, e in enumerate(out) if e.opportunity is not None and e.opportunity.label != "watch"
    ][:top]
    gate = asyncio.Semaphore(concurrency)
    stopped = False

    async def one(i: int) -> ReviewOutput | None:
        nonlocal stopped
        async with gate:
            if stopped:
                return None
            try:
                return await _review(out[i], spec, run=run, session=session)
            except (BudgetExceeded, ConfigError):
                stopped = True  # out of budget, or no deep model configured: show as ranked
                return None
            except _FAILURES:
                return None

    reviews = await asyncio.gather(*(one(i) for i in picks))
    passed = held = failed = 0
    for i, review in zip(picks, reviews, strict=True):
        entry = out[i]
        o = entry.opportunity
        assert o is not None
        if review is None:
            failed += 1  # not reviewed: shown as before, never held back on a failure of ours
            continue
        refs = {c.ref for c in entry.candidate.claims}
        cited = [r for r in (ref_of(x) for x in review.cited_refs) if r in refs]
        quotes = [c.source_quote for c in entry.candidate.claims if c.ref in cited]
        note = review.note.strip()
        if not note or not numbers_grounded(note, quotes):
            note = ""
        if review.worthy and cited:
            passed += 1
            line = f"Reviewed: worth a call today. {note}".strip()
            out[i] = entry.model_copy(update={"rank_reasons": [line, *entry.rank_reasons]})
        else:
            held += 1
            why = note or "the reviewer was not sure enough to put it in front of you today"
            out[i] = entry.model_copy(
                update={
                    "opportunity": o.model_copy(update={"label": "watch"}),
                    "rank_reasons": [f"Held back by the review: {why}", *entry.rank_reasons],
                }
            )
    notes = [f"review: {passed} passed, {held} held back, {failed} not reviewed"] if picks else []
    return out, notes
