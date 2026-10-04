"""T5.4: the skeptic with a fake client (no network)."""

from __future__ import annotations

from typing import Any

import pytest

from northvaine.brain import llm
from northvaine.brain.budget import RunContext
from northvaine.radar.court import skeptic
from northvaine.radar.models import GateDecision, RejectedAs
from tests.radar.test_gate import SPEC, FakeClient, make_candidate

MODEL = "nvidia/Nemotron-3_5-Lightning"

PASSED = GateDecision(
    passed=True,
    rejected_as=None,
    by="llm",
    reason="builder",
    direct_buyer=True,
    buyer_reason="plans a plant",
    demand_reason="needs the offer",
    suggested_action=None,
    cited_refs=["C1"],
)


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch, clean_settings: None) -> None:
    monkeypatch.setenv("MODEL_MID", MODEL)
    monkeypatch.setenv("DAILY_BUDGET_USD", "10")
    monkeypatch.setenv("TOTAL_BUDGET_USD", "29")
    llm.get_settings.cache_clear()


async def run_skeptic(reply: dict[str, Any]) -> tuple[Any, FakeClient]:
    client = FakeClient(reply)
    with llm.client_override(client):
        finding = await skeptic(make_candidate(), PASSED, SPEC, run=RunContext())
    return finding, client


async def test_refuses_a_gate_that_did_not_pass() -> None:
    failed = PASSED.model_copy(update={"passed": False, "rejected_as": RejectedAs.COMPETITOR})
    client = FakeClient({"against": [], "open_questions": []})
    with llm.client_override(client), pytest.raises(ValueError):
        await skeptic(make_candidate(), failed, SPEC, run=RunContext())
    assert client.requests == []


async def test_valid_points_are_kept_with_refs() -> None:
    finding, client = await run_skeptic(
        {
            "against": [
                {"claim_ref": "C1", "why": "only a plan for 12 lines, not an order"},
                {"claim_ref": "C7", "why": "unknown ref"},
                {"claim_ref": "C1", "why": "it will cost 50 million"},
            ],
            "open_questions": ["who runs procurement", "is the 77 budget real"],
        }
    )
    assert finding.stance == "against"
    assert [(p.claim_ref, p.why) for p in finding.against] == [
        ("C1", "only a plan for 12 lines, not an order")
    ]
    assert finding.open_questions == ["who runs procurement"]
    assert client.requests[0]["model"] == MODEL


async def test_all_invalid_points_mean_unknown() -> None:
    finding, _ = await run_skeptic(
        {"against": [{"claim_ref": "C9", "why": "x"}], "open_questions": ["who decides"]}
    )
    assert finding.stance == "unknown" and finding.against == []
    assert finding.open_questions == ["who decides"]


async def test_request_fences_inputs_and_asks_for_no_rank_or_score() -> None:
    _, client = await run_skeptic({"against": [], "open_questions": []})
    prompt = client.prompt
    for label in ("CLAIMS", "CANDIDATE_NAME", "DEMAND_REASON"):
        assert f"-----BEGIN {label} DATA" in prompt
    stripped = " ".join(prompt.split()).replace("You do not score or rank anything.", "")
    for word in ("rank", "score", "strength"):
        assert word not in stripped.lower()
