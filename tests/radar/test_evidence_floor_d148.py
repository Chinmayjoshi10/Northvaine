"""D148: the evidence floor. A lead is shown only as a company in the client's markets with proof it
deals in the client's kind of product; everything else is held, with its reason, never deleted."""

from __future__ import annotations

from datetime import date

from northvaine.api.leadview import opening_line, opportunity_view
from northvaine.radar.models import ClientSpec, RadarStream, RankedEntry
from northvaine.radar.opportunity import (
    HELD_COUNTRY,
    HELD_EVIDENCE,
    HELD_MAKER,
    HELD_MARKET,
    HELD_PROJECT,
    hold_reason,
    order_opportunities,
)
from tests.radar.test_fit import entry

TODAY = date(2026, 11, 14)
SPEC = ClientSpec.model_validate(
    {
        "id": "demo",
        "offer": "Widgets and fittings for builders",
        "markets": ["GB", "FR"],
        "offer_terms": ["widgets"],
        "product_codes": [],
        "sensors": {},
        "channel": "both",
    }
)


def _lead(**update: object) -> RankedEntry:
    """A proven importer in a client market: shown."""
    base = entry("importer_of_record", RadarStream.TRADE)
    fields = {"evidence_level": "proven_buyer", "requirement": "stated", **update}
    country = fields.pop("country", "GB")
    return base.model_copy(
        update={**fields, "candidate": base.candidate.model_copy(update={"country": country})}
    )


def test_a_proven_buyer_in_a_client_market_is_shown() -> None:
    assert hold_reason(_lead(), SPEC) is None
    assert hold_reason(_lead(evidence_level="company_fit"), SPEC) is None


def test_each_missing_proof_holds_the_entry_with_its_reason() -> None:
    assert hold_reason(_lead(site_role="makes"), SPEC) == HELD_MAKER
    assert hold_reason(_lead(country=None), SPEC) == HELD_COUNTRY
    assert hold_reason(_lead(country="US"), SPEC) == HELD_MARKET
    assert hold_reason(_lead(evidence_level="no_evidence"), SPEC) == HELD_EVIDENCE
    assert hold_reason(_lead(evidence_level="generic_mention"), SPEC) == HELD_EVIDENCE
    assert hold_reason(_lead(requirement="inferred"), SPEC) == HELD_EVIDENCE
    tender = entry("demand_source", RadarStream.TENDER).model_copy(
        update={"evidence_level": "project_requirement", "requirement": "stated"}
    )
    tender = tender.model_copy(
        update={"candidate": tender.candidate.model_copy(update={"country": "FR"})}
    )
    assert hold_reason(tender, SPEC) == HELD_PROJECT


def test_an_old_run_record_without_evidence_levels_falls_back_to_the_requirement() -> None:
    assert hold_reason(_lead(evidence_level=None), SPEC) is None
    assert hold_reason(_lead(evidence_level=None, requirement="inferred"), SPEC) == HELD_EVIDENCE


def test_with_the_floor_held_entries_go_after_every_lead_as_watch_with_the_reason_first() -> None:
    funder = _lead(country=None, evidence_level="no_evidence", requirement="inferred")
    funder = funder.model_copy(
        update={"rank": 1, "candidate": funder.candidate.model_copy(update={"key": "x:f"})}
    )
    buyer = _lead().model_copy(update={"rank": 2})
    out = order_opportunities([funder, buyer], TODAY, SPEC, floor=True)
    assert [e.candidate.key for e in out] == [buyer.candidate.key, "x:f"]
    held = out[1]
    assert held.opportunity is not None and held.opportunity.label == "watch"
    assert held.opportunity.held == HELD_COUNTRY
    assert held.rank_reasons[0] == HELD_COUNTRY
    # shown where a lead shows its strength; no opening line claims anything about it
    view = opportunity_view(held)
    assert view is not None and view.words == HELD_COUNTRY
    assert opening_line(held, "widgets") is None
    # ordering again does not repeat the reason
    again = order_opportunities(out, TODAY, SPEC, floor=True)
    assert again[1].rank_reasons.count(HELD_COUNTRY) == 1


def test_without_the_floor_nothing_is_held() -> None:
    funder = _lead(country=None, evidence_level="no_evidence")
    out = order_opportunities([funder], TODAY, SPEC)
    assert out[0].opportunity is not None and out[0].opportunity.held is None


def test_a_project_line_needs_a_dated_record_naming_the_company() -> None:
    project = entry("awarded_contractor").model_copy(
        update={"evidence_level": "company_fit", "requirement": "stated"}
    )
    [assessed] = order_opportunities([project], TODAY, SPEC)
    assert assessed.opportunity is not None and assessed.opportunity.play == "project"
    assert opening_line(assessed, "widgets") is None
