"""D123: the fit judge reads who buys; the own-name rule never overrides resells or uses."""

from __future__ import annotations

import pytest

from northvaine.brain.prompts import load_prompt
from northvaine.core.settings import Settings
from northvaine.radar.fit import own_name_rule
from northvaine.radar.linefit import JudgeResult, _find_quote
from tests.radar.test_brands_d121 import MARKET, _company

ON = Settings(_env_file=None)


@pytest.mark.parametrize("role", ["resells", "uses"])
def test_own_name_rule_never_overrides_the_judges_resells_or_uses(role: str) -> None:
    c = _company("Acme Cooling UK Ltd").candidate
    verdict = JudgeResult(role=role, brands=["Acme"])
    assert own_name_rule(c, verdict, MARKET, ON).role == role


@pytest.mark.parametrize("role", ["other", "unclear"])
def test_own_name_rule_still_fills_in_when_the_judge_gave_no_role(role: str) -> None:
    c = _company("Acme Cooling UK Ltd").candidate
    verdict = JudgeResult(role=role, brands=["Acme"])
    assert own_name_rule(c, verdict, MARKET, ON).role == "makes"


def test_quote_in_capitals_matches_only_with_any_case_and_keeps_the_page_text() -> None:
    sent = [("https://acme.example/", "About us. WE MANUFACTURE cabinets in Leeds.")]
    assert _find_quote("We manufacture cabinets", sent) is None
    found = _find_quote("We manufacture cabinets", sent, any_case=True)
    assert found == ("https://acme.example/", "WE MANUFACTURE cabinets")


def test_prompt_v4_reads_who_buys_and_fences_the_page_text() -> None:
    prompt = load_prompt("radar_line_fit", version=4)
    assert "{buyer_roles}" in prompt.template and "{not_buyers}" in prompt.template
    assert prompt.untrusted_vars == {"company_name", "pages"}
    assert "is never makes" in prompt.template


def test_d124_a_possible_competitor_ranks_last_in_its_level_with_the_quote() -> None:
    from northvaine.radar.brief import apply_fit_order
    from northvaine.radar.models import SiteRoleQuote
    from tests.radar.test_lines_d118 import _entry

    maker = _entry("a", 1, term="marble").model_copy(
        update={
            "site_role": "makes",
            "site_role_quote": SiteRoleQuote(
                url="u", quote="We manufacture slabs", fingerprint="f"
            ),
        }
    )
    other = _entry("b", 2, term="marble")
    out = apply_fit_order([maker, other])
    assert [e.candidate.key for e in out] == [other.candidate.key, maker.candidate.key]
    assert any(r.startswith('Possible competitor: its own site reads "We manufacture slabs"')
               for r in out[1].rank_reasons)  # fmt: skip
