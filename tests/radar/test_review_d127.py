"""D127: the senior review holds back what it would not call, with its reason, never deletes."""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from northvaine.brain.budget import RunContext
from northvaine.brain.errors import LlmInvalidOutput
from northvaine.brain.prompts import load_prompt
from northvaine.radar import review as review_module
from northvaine.radar.opportunity import order_opportunities
from northvaine.radar.review import ReviewOutput, review_top
from tests.radar.test_fit import entry
from tests.radar.test_opportunity_d125 import SPEC, TODAY, _claim, _event, _with


def _top(n: int = 3) -> list[Any]:
    out = []
    for k in range(n):
        e = _with(
            entry("awarded_contractor"),
            key=f"GB:{k}",
            name=f"Granite Co {k}",
            events=[_event("contract_awarded", date(2026, 10, 20))],
            claims=[_claim(f"Title [eng]: Granite works {k}", "C1")],
        )
        out.append(e.model_copy(update={"rank": k + 1}))
    return order_opportunities(out, TODAY, SPEC)


def _fake(monkeypatch: pytest.MonkeyPatch, replies: dict[str, Any]) -> None:
    async def fake(entry, spec, *, run, session):
        reply = replies[entry.candidate.name]
        if isinstance(reply, Exception):
            raise reply
        return reply

    monkeypatch.setattr(review_module, "_review", fake)


async def test_worthy_leads_pass_and_doubtful_ones_are_held_back_with_the_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake(
        monkeypatch,
        {
            "Granite Co 0": ReviewOutput(
                worthy=True, cited_refs=["C1"], note="Fresh contract for granite works."
            ),
            "Granite Co 1": ReviewOutput(
                worthy=False, cited_refs=["C1"], note="Repairs only, no new stone."
            ),
            "Granite Co 2": ReviewOutput(
                worthy=True, cited_refs=[], note="Looks fine."
            ),  # cites nothing
        },
    )
    out, notes = await review_top(_top(), SPEC, top=10, run=RunContext())
    by = {e.candidate.name: e for e in out}
    assert by["Granite Co 0"].opportunity.label != "watch"
    assert by["Granite Co 0"].rank_reasons[0].startswith("Reviewed: worth a call today.")
    assert by["Granite Co 1"].opportunity.label == "watch"
    assert (
        by["Granite Co 1"].rank_reasons[0] == "Held back by the review: Repairs only, no new stone."
    )
    assert by["Granite Co 2"].opportunity.label == "watch"  # an uncited yes is not trusted
    assert len(out) == 3  # nothing deleted
    assert notes == ["review: 1 passed, 2 held back, 0 not reviewed"]


async def test_a_failed_review_never_holds_a_lead_back_and_numbers_must_be_grounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake(
        monkeypatch,
        {
            "Granite Co 0": LlmInvalidOutput("bad json"),
            "Granite Co 1": ReviewOutput(
                worthy=True, cited_refs=["C1"], note="Worth 250000 in orders."
            ),
            "Granite Co 2": ReviewOutput(worthy=True, cited_refs=["C1"], note="Good."),
        },
    )
    out, notes = await review_top(_top(), SPEC, top=10, run=RunContext())
    by = {e.candidate.name: e for e in out}
    assert by["Granite Co 0"].opportunity.label != "watch"
    assert by["Granite Co 1"].rank_reasons[0] == "Reviewed: worth a call today."  # figure dropped
    assert notes == ["review: 2 passed, 0 held back, 1 not reviewed"]


def test_the_prompt_fences_the_lead_and_reads_the_clients_buyer_model() -> None:
    prompt = load_prompt("radar_review", version=1)
    assert prompt.untrusted_vars == {"candidate_name", "claims", "why_now", "against"}
    assert "{buyer_roles}" in prompt.template and "{not_buyers}" in prompt.template
