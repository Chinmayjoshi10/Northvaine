"""D125: opportunities ranked by intent, fit and confidence; off-target leads removed by code."""

from __future__ import annotations

from datetime import date

from northvaine.radar.brief import off_target
from northvaine.radar.models import (
    CandidateClaim,
    CandidateEvent,
    ClientSpec,
    FitEvidence,
    RadarStream,
    RankedEntry,
    RegisterFacts,
)
from northvaine.radar.opportunity import assess, order_opportunities
from tests.radar.test_fit import entry

TODAY = date(2026, 10, 23)
SPEC = ClientSpec.model_validate(
    {
        "id": "demo",
        "offer": "Natural stone wall panels and paving",
        "markets": ["GB", "US", "DE"],
        "offer_terms": ["natural stone", "granite", "paving"],
        "related_terms": ["masonry"],
        "product_codes": ["cpv:44912000"],
        "sensors": {},
        "channel": "both",
    }
)


def _claim(quote: str, ref: str = "C1") -> CandidateClaim:
    return CandidateClaim.model_validate(
        {
            "ref": ref,
            "fingerprint": ref,
            "document_id": "00000000-0000-0000-0000-000000000001",
            "statement": f"The notice record states {quote}",
            "source_quote": quote,
            "url": "https://example.org/record",
            "source_name": "ted",
            "available_at": None,
            "evidence_kind": "structured",
            "verified_by": "code",
            "upgraded_from": None,
        }
    )


def _event(kind: str, when: date) -> CandidateEvent:
    return CandidateEvent(
        event_type=kind,
        description=kind,
        occurred_on=when,
        available_at=None,
        claim_refs=[],
        slots={},
        fingerprint=kind,
    )


def _with(e: RankedEntry, **candidate: object) -> RankedEntry:
    return e.model_copy(update={"candidate": e.candidate.model_copy(update=candidate)})


def _fit(e: RankedEntry) -> RankedEntry:
    quote = "We stock natural stone paving."
    fits = [
        FitEvidence(url="u", quote=quote, term="natural stone", level="stated", fingerprint="f")
    ]
    return e.model_copy(update={"fit_level": "stated", "company_fit": fits})


def _register(**dates: date) -> RegisterFacts:
    return RegisterFacts(number="01234567", name="ACME LIMITED", status="active", **dates)


def test_a_fresh_contract_naming_the_product_is_approach_now() -> None:
    e = _with(
        entry("awarded_contractor"),
        name="Hilgartner Natural Stone Co",
        events=[_event("contract_awarded", date(2026, 10, 21))],
    )
    o = assess(e, TODAY, SPEC)
    assert (o.label, o.play, o.intent, o.fit) == ("approach_now", "project", 3, 2)
    assert "contract awarded on 2026-10-21" in o.why_now


def test_a_moved_office_alone_is_only_a_hint_and_stays_on_the_watch_list() -> None:
    e = _with(
        entry("importer", RadarStream.TRADE),
        company_register=_register(office_moved_on=date(2026, 9, 21)),
    )
    o = assess(e, TODAY, SPEC)
    assert o.intent == 1 and o.label == "watch"


def test_new_owner_plus_own_site_plus_trade_is_connected() -> None:
    e = _fit(
        _with(
            entry("importer", RadarStream.TRADE),
            company_register=_register(control_changed_on=date(2026, 9, 23)),
        )
    )
    o = assess(e, TODAY, SPEC)
    assert o.label == "connected" and o.confidence >= 3 and o.fit == 2


def test_no_new_signal_is_watch_and_a_competitor_always_goes_last() -> None:
    plain = _fit(entry("importer", RadarStream.TRADE))
    assert assess(plain, TODAY, SPEC).label == "watch"
    maker = _with(
        entry("awarded_contractor"),
        name="Granite Makers",
        events=[_event("contract_awarded", date(2026, 10, 20))],
    ).model_copy(update={"site_role": "makes", "rank": 1})
    buyer = _with(
        entry("awarded_contractor"),
        key="GB:buyer",
        name="Granite Buyers",
        events=[_event("contract_awarded", date(2026, 10, 1))],
    ).model_copy(update={"rank": 2})
    out = order_opportunities([maker, buyer], TODAY, SPEC)
    assert [e.candidate.name for e in out] == ["Granite Buyers", "Granite Makers"]
    assert [e.rank for e in out] == [1, 2]
    assert out[0].rank_reasons[0].startswith("Approach now:")


def test_off_target_drops_other_markets_and_unrelated_contracts_but_keeps_coded_records() -> None:
    abroad = _with(
        entry("awarded_contractor"), key="SG:hotel", country="SG", name="Hotel Singapore"
    )
    unrelated = _with(
        entry("awarded_contractor"),
        key="US:x",
        country="US",
        name="Fiber Business Ltd",
        claims=[_claim("Title [eng]: Steam tunnel repairs")],
    )
    named = _with(
        entry("awarded_contractor"),
        key="US:y",
        country="US",
        name="Stone Works",
        claims=[_claim("Title [eng]: Granite countertop installation")],
    )
    german = _with(
        entry("awarded_contractor"),
        key="DE:z",
        country="DE",
        name="Pflasterbau GmbH",
        claims=[_claim("Title [deu]: Pflasterarbeiten Marktplatz"), _claim("cpv: 44912000", "C2")],
    )
    kept, off = off_target([e.candidate for e in (abroad, unrelated, named, german)], SPEC)
    assert [c.name for c in kept] == ["Stone Works", "Pflasterbau GmbH"]
    assert {o.candidate.name for o in off} == {"Hotel Singapore", "Fiber Business Ltd"}
    assert all(o.gate.by == "code" and o.gate.reason.startswith("Off target") for o in off)
