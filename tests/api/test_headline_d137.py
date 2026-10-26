"""D137: a lead in plain words - who did what, and why it matters to the client."""

from __future__ import annotations

from datetime import date

from northvaine.api.headline import display_name, headline, why_you
from northvaine.api.views import _row
from tests.api.test_leadview_d125 import _award_entry, _with_opportunity
from tests.radar.test_fit import entry
from tests.radar.test_opportunity_d125 import SPEC, TODAY, _register, _with


def test_display_name_reads_like_a_name() -> None:
    assert display_name("ACME TRADING LIMITED") == "Acme Trading"
    assert display_name("COMPTOIR DES REVETEMENTS") == "Comptoir des Revetements"
    assert display_name("Acme Trading Ltd") == "Acme Trading"
    assert display_name("Mixed Case Works") == "Mixed Case Works"


def test_no_opportunity_means_no_headline() -> None:
    e = entry("awarded_contractor")
    assert e.opportunity is None
    assert headline(e) is None


def test_a_register_change_reads_as_what_the_company_did() -> None:
    e = _with(
        entry("awarded_contractor"),
        name="ACME LIMITED",
        events=[],
        company_register=_register(control_changed_on=date(2026, 10, 1)),
    )
    line = headline(_with_opportunity(e))
    assert line is not None and line.startswith("Acme")
    assert "changed owner on 2026-10-01" in line


def test_why_you_uses_only_the_stated_fit_and_the_client_words() -> None:
    e = _with_opportunity(_award_entry())
    assert (
        why_you(e, list(SPEC.offer_terms))
        == "Their own site sells natural stone, which you supply."
    )
    bare = e.model_copy(update={"company_fit": [], "matched_lines": []})
    assert why_you(bare, list(SPEC.offer_terms)) is None  # nothing stated: nothing said


def test_the_row_carries_the_plain_words() -> None:
    row = _row(_with_opportunity(_award_entry()), TODAY, "", list(SPEC.offer_terms))
    assert row.headline and row.headline.endswith(".")
    assert row.why_you and "natural stone" in row.why_you
