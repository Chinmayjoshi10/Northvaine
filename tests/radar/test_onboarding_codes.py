"""Onboarding code check: each customs code's tariff description must describe the client's own
products. No network, no model: the LLM call is replaced."""

from __future__ import annotations

from types import SimpleNamespace

from northvaine.brain.budget import RunContext
from northvaine.brain.prompts import load_prompt
from northvaine.radar import onboarding
from northvaine.radar.onboarding import CodeCheck, CodeChecks, Proposal, check_codes

DESCRIBED = {
    "111111": "Frames of material A",
    "222222": "Frames of material B",
}


def _fake(checks: list[CodeCheck]):
    async def fake(**kwargs):
        assert kwargs["purpose"] == "onboarding_codes"
        return SimpleNamespace(value=CodeChecks(checks=checks))

    return fake


async def _run() -> tuple[list[str], list[str]]:
    return await check_codes(
        "We make frames of material A.", ["frame"], DESCRIBED, run=RunContext()
    )


async def test_matching_code_kept_and_mismatch_dropped_with_note(monkeypatch) -> None:
    monkeypatch.setattr(
        onboarding,
        "complete_json",
        _fake(
            [
                CodeCheck(code="111111", matches=True, reason="same product and material"),
                CodeCheck(code="222222", matches=False, reason="a different material"),
            ]
        ),
    )
    kept, notes = await _run()
    assert kept == ["111111"]
    assert notes == ["customs code 222222 does not match your products: a different material"]


async def test_llm_failure_keeps_all_codes(monkeypatch) -> None:
    async def boom(**kwargs):
        raise RuntimeError("down")

    monkeypatch.setattr(onboarding, "complete_json", boom)
    kept, notes = await _run()
    assert kept == ["111111", "222222"]
    assert notes == []


async def test_code_without_verdict_is_kept(monkeypatch) -> None:
    monkeypatch.setattr(
        onboarding, "complete_json", _fake([CodeCheck(code="222222", matches=False, reason="x")])
    )
    kept, _ = await _run()
    assert kept == ["111111"]


async def test_no_codes_means_no_call(monkeypatch) -> None:
    async def boom(**kwargs):
        raise AssertionError("must not call")

    monkeypatch.setattr(onboarding, "complete_json", boom)
    assert await check_codes("x", [], {}, run=RunContext()) == ([], [])


def test_prompt_loads_and_proposal_has_descriptions() -> None:
    prompt = load_prompt("onboarding_codes", version=1)
    assert prompt.name == "onboarding_codes"
    p = Proposal(offer="x")
    assert p.hs_descriptions == {}


def test_the_codes_prompt_renders_with_its_variables() -> None:
    # a literal brace in the prompt once made every call fail silently (all codes kept)
    from northvaine.brain.fencing import Untrusted
    from northvaine.brain.prompts import load_prompt

    text = load_prompt("onboarding_codes", version=1).render(
        offer=Untrusted("An offer"), product_terms=Untrusted("a, b"), codes="123456: a product"
    )
    assert "123456: a product" in text and '{"checks"' in text
