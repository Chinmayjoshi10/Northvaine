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


def test_d156_a_quiet_day_is_filled_with_accounts_to_work_never_with_held_entries() -> None:
    from northvaine.core.settings import Settings
    from northvaine.radar.edition import daily_edition, label_entries
    from northvaine.radar.models import CandidateEvent

    def keyed(e: RankedEntry, key: str, rank: int) -> RankedEntry:
        return e.model_copy(
            update={"rank": rank, "candidate": e.candidate.model_copy(update={"key": key})}
        )

    news = CandidateEvent(
        event_type="contract_awarded",
        description="won a contract",
        occurred_on=date(2026, 11, 10),
        available_at=None,
        claim_refs=[],
        slots={},
        fingerprint="n",
    )
    fresh = keyed(_lead(), "GB:fresh", 1)
    fresh = fresh.model_copy(
        update={"candidate": fresh.candidate.model_copy(update={"events": [news]})}
    )
    quiet = [keyed(_lead(), f"GB:quiet{i}", 2 + i) for i in range(3)]
    held = keyed(_lead(country=None), "x:held", 6)
    maker = keyed(_lead(site_role="makes"), "GB:maker", 7)
    ordered = order_opportunities([fresh, *quiet, held, maker], TODAY, SPEC, floor=True)
    on = Settings(_env_file=None)
    edition = daily_edition(label_entries(ordered, TODAY, on), on)
    keys = {e.candidate.key for e in edition}
    assert {"GB:quiet0", "GB:quiet1", "GB:quiet2"} <= keys
    assert "x:held" not in keys and "GB:maker" not in keys
    assert len(edition) <= on.radar_daily_quota
    filled = [e for e in edition if e.candidate.key.startswith("GB:quiet")]
    assert all(e.label == "account_to_work" for e in filled)
    off = Settings(_env_file=None, radar_edition_fill=False)
    plain = daily_edition(label_entries(ordered, TODAY, off), off)
    assert not any(e.candidate.key.startswith("GB:quiet") for e in plain)
