"""D125: the source chain (dots), the opportunity on the view and the line to open with."""

from __future__ import annotations

import re
from datetime import date

from northvaine.api.leadview import dots, opening_line, opportunity_view, supply_phrase
from northvaine.api.views import _row
from northvaine.radar.models import (
    AgainstPoint,
    CandidateClaim,
    ClientSpec,
    FitEvidence,
    RadarStream,
    RankedEntry,
    SkepticFinding,
)
from northvaine.radar.opportunity import assess
from tests.radar.test_fit import entry
from tests.radar.test_opportunity_d125 import SPEC, TODAY, _claim, _event, _register, _with

PRICE_WORDS = re.compile(r"price|discount|cost|\$|£|€|%|payment|terms|deliver", re.IGNORECASE)


def _award_entry() -> RankedEntry:
    award = _claim("Winner [C1]: Hilgartner Natural Stone Co", "C1")
    changed = _register(control_changed_on=date(2026, 9, 1))
    e = _with(
        entry("awarded_contractor"),
        name="Hilgartner Natural Stone Co",
        events=[
            _event("contract_awarded", date(2026, 10, 21)).model_copy(
                update={"claim_refs": ["C1"], "description": "Contract awarded for a plaza"}
            )
        ],
        claims=[award],
        company_register=changed,
    )
    fits = [
        FitEvidence(
            url="https://acme.example/products",
            quote="We stock natural stone paving.",
            term="natural stone",
            level="stated",
            fingerprint="f",
        )
    ]
    skeptic = SkepticFinding(
        stance="against",
        against=[AgainstPoint(claim_ref="C1", why="could be a subcontract only")],
        open_questions=[],
    )
    return e.model_copy(update={"fit_level": "stated", "company_fit": fits, "skeptic": skeptic})


def test_dots_are_dated_newest_first_with_kinds_and_source_names() -> None:
    found = dots(_award_entry())
    kinds = [d.kind for d in found]
    assert kinds[:2] == ["contract", "register"]
    assert found[0].date == "2026-10-21" and found[1].date == "2026-09-01"
    assert found[0].source == "EU tenders (TED)"
    assert found[0].url == "https://example.org/record" and found[0].ref == "C1"
    assert found[1].source == "Companies House"
    assert "website" in kinds and "check" in kinds
    site = next(d for d in found if d.kind == "website")
    assert site.source == "Company website, read with Tavily"
    assert site.url == "https://acme.example/products"
    checks = [d for d in found if d.kind == "check"]
    assert any(d.line.startswith("Against: could be") for d in checks)
    assert {d.source for d in checks} == {"Nemotron on Nebius"}
    # dated facts first, undated after
    dated = [bool(d.date) for d in found]
    assert dated == sorted(dated, reverse=True)


def test_an_unknown_source_name_is_shown_as_it_is() -> None:
    claim: CandidateClaim = _claim("Winner [C1]: X", "C1").model_copy(
        update={"source_name": "some-new-source"}
    )
    e = _with(
        entry("awarded_contractor"),
        claims=[claim],
        events=[
            _event("contract_awarded", date(2026, 10, 1)).model_copy(update={"claim_refs": ["C1"]})
        ],
    )
    assert dots(e)[0].source == "some-new-source"


def test_the_trade_record_is_a_dot_with_its_source() -> None:
    claim = _claim("Commodity 12345678: imported in 4 months", "C1").model_copy(
        update={"source_name": "hmrc", "url": "https://hmrc.example/r"}
    )
    ev = _event("imports_recorded", date(2026, 9, 1)).model_copy(
        update={"slots": {"last_month": "2026-09", "first_month": "2026-01"}, "claim_refs": ["C1"]}
    )
    e = _with(
        entry("importer", RadarStream.TRADE), claims=[claim], events=[ev], stream=RadarStream.TRADE
    )
    found = dots(e)
    assert found[0].kind == "trade"
    assert found[0].source == "HMRC import records"
    assert found[0].url == "https://hmrc.example/r"


def _with_opportunity(e: RankedEntry) -> RankedEntry:
    return e.model_copy(update={"opportunity": assess(e, TODAY, SPEC)})


def test_the_opportunity_view_has_the_display_word() -> None:
    view = opportunity_view(_with_opportunity(_award_entry()))
    assert view is not None
    assert view.label == "connected" and view.word == "Connected"
    assert "intent" in view.words and "contract awarded" in view.why_now
    assert view.play == "project"


def test_older_entries_without_an_opportunity_give_nulls() -> None:
    e = _award_entry()
    assert e.opportunity is None
    row = _row(e, TODAY, "natural stone")
    assert row.opportunity is None and row.say is None
    assert opportunity_view(e) is None and opening_line(e, "natural stone") is None
    assert len(row.dots) >= 1  # the dots still come from what the entry holds


def test_say_per_play_uses_the_priority_line_and_names_no_price_or_term() -> None:
    spec = ClientSpec.model_validate(
        {
            **SPEC.model_dump(),
            "catalogue_lines": [{"name": "Sandstone paving", "terms": ["sandstone"]}],
        }
    )
    supply = supply_phrase(spec, "fallback offer")
    assert supply == "Sandstone paving"
    assert supply_phrase(SPEC, "x") == "natural stone"
    assert supply_phrase(None, "The offer") == "The offer"

    project = _with_opportunity(_award_entry())
    line = opening_line(project, supply)
    assert line is not None and "sandstone paving" in line and "samples" in line
    assert "2026-10-21" not in line

    partner_base = _with_opportunity(_award_entry())
    partner = partner_base.model_copy(
        update={"opportunity": partner_base.opportunity.model_copy(update={"play": "partner"})}
    )
    pline = opening_line(partner, supply)
    assert pline is not None and pline.startswith("We noticed ") and "sandstone paving" in pline

    claim = _claim("Commodity 68029300: imported in 4 months", "C1").model_copy(
        update={"source_name": "hmrc"}
    )
    account_base = _with(
        entry("importer", RadarStream.TRADE), claims=[claim], stream=RadarStream.TRADE
    )
    account = account_base.model_copy(
        update={"opportunity": project.opportunity.model_copy(update={"play": "account"})}
    )
    aline = opening_line(account, supply)
    assert aline is not None and "Commodity 68029300" in aline and "second source" in aline

    for text in (line, pline, aline):
        assert not PRICE_WORDS.search(text), text


def test_d134_a_partner_with_no_dated_reason_gets_a_line_that_claims_nothing() -> None:
    from northvaine.api.leadview import opening_line
    from northvaine.radar.models import Opportunity

    entry = _award_entry().model_copy(
        update={
            "opportunity": Opportunity(
                label="relationship",
                play="partner",
                intent=0,
                fit=3,
                confidence=2,
                latest=None,
                why_now="",
                words="No new signal · Strong fit · 2 sources agree",
            )
        }
    )
    line = opening_line(entry, "Design wall coverings")
    assert line == (
        "We make design wall coverings and work with distributors like you; "
        "would a sample range be useful?"
    )
    assert "noticed" not in line and "growth" not in line
