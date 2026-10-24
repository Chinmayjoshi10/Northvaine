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


def _claim(quote: str, ref: str = "C1", kind: str = "structured") -> CandidateClaim:
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
            "evidence_kind": kind,
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


def test_the_edition_is_the_top_five_non_watch_opportunities() -> None:
    from northvaine.core.settings import Settings
    from northvaine.radar.edition import daily_edition

    entries = []
    for n in range(8):
        e = _with(
            entry("awarded_contractor"),
            key=f"GB:{n}",
            name=f"Granite Co {n}",
            events=[_event("contract_awarded", date(2026, 10, 20))] if n != 1 else [],
        )
        entries.append(e.model_copy(update={"rank": n + 1}))
    ordered = order_opportunities(entries, TODAY, SPEC)
    picked = daily_edition(ordered, Settings(_env_file=None))
    assert len(picked) == 5
    assert all(e.opportunity.label != "watch" for e in picked)
    assert [e.rank for e in picked] == [1, 2, 3, 4, 5]


def test_d128_news_of_the_clients_kind_of_project_counts_but_a_vague_tender_does_not() -> None:
    spec = SPEC.model_copy(update={"need_triggers": ["luxury villa project", "hotel opening"]})
    villa = _with(
        entry("awarded_contractor", RadarStream.ANNOUNCEMENT),
        key="AE:dev",
        country=None,
        name="Gulf Developer",
        claims=[
            _claim(
                "Gulf Developer launches a luxury villa community on the coast", kind="full_text"
            )
        ],
        events=[_event("facility_opened", date(2026, 10, 10))],
    )
    tender = _with(
        entry("awarded_contractor", RadarStream.TENDER),
        key="DE:t",
        country="DE",
        name="Stadt Beispiel",
        claims=[_claim("Title [deu]: Fassadensanierung Schule")],
        events=[_event("tender_published", date(2026, 10, 10))],
    )
    kept, _ = off_target([villa.candidate, tender.candidate], spec)
    assert [c.name for c in kept] == ["Gulf Developer"]  # the tender names neither product nor code
    assert assess(villa, TODAY, spec).label == "approach_now"
    tender = tender.model_copy(update={"requirement": "inferred"})  # its title names no product
    assert assess(tender, TODAY, spec).label == "watch"  # a vague tender is a project to watch


def test_d129_a_big_fitting_distributor_is_a_relationship_and_news_ranks_it_higher() -> None:
    quiet = _fit(_with(entry("importer", RadarStream.TRADE), key="GB:q", name="Quiet Stone Ltd"))
    quiet = quiet.model_copy(
        update={
            "site_role": "resells",
            "candidate": quiet.candidate.model_copy(
                update={"company_register": _register(accounts_type="full")}
            ),
        }
    )
    assert assess(quiet, TODAY, SPEC).label == "relationship"
    small = quiet.model_copy(
        update={"candidate": quiet.candidate.model_copy(update={"company_register": _register()})}
    )
    assert assess(small, TODAY, SPEC).label == "watch"  # not big, no news: watch
    busy = quiet.model_copy(
        update={
            "candidate": quiet.candidate.model_copy(
                update={
                    "key": "GB:b",
                    "name": "Busy Stone Ltd",
                    "company_register": _register(
                        accounts_type="full", control_changed_on=date(2026, 9, 30)
                    ),
                }
            )
        }
    )
    out = order_opportunities(
        [quiet.model_copy(update={"rank": 1}), busy.model_copy(update={"rank": 2})], TODAY, SPEC
    )
    assert out[0].candidate.name == "Busy Stone Ltd"  # an update that leads to buying ranks higher


def test_d129_the_edition_takes_the_best_of_each_kind_first() -> None:
    from northvaine.core.settings import Settings
    from northvaine.radar.edition import daily_edition

    projects = [
        _with(
            entry("awarded_contractor"),
            key=f"GB:p{n}",
            name=f"Granite Co {n}",
            events=[_event("contract_awarded", date(2026, 10, 20))],
        ).model_copy(update={"rank": n + 1})
        for n in range(6)
    ]
    partner = _fit(_with(entry("importer", RadarStream.TRADE), key="GB:d", name="Big Distributor"))
    partner = partner.model_copy(
        update={
            "rank": 7,
            "site_role": "resells",
            "candidate": partner.candidate.model_copy(
                update={"company_register": _register(accounts_type="group")}
            ),
        }
    )
    picked = daily_edition(
        order_opportunities([*projects, partner], TODAY, SPEC), Settings(_env_file=None)
    )
    assert len(picked) == 5
    assert "Big Distributor" in [e.candidate.name for e in picked]  # not crowded out by projects


def _importer(months: list[str], code_months: dict[str, list[str]]) -> RankedEntry:
    e = entry("importer", RadarStream.TRADE)
    ev = _event("imports_recorded", date(2026, 9, 1)).model_copy(
        update={"slots": {"months": months, "code_months": code_months, "last_month": months[-1]}}
    )
    return e.model_copy(update={"candidate": e.candidate.model_copy(update={"events": [ev]})})


def test_d131_import_record_changes_new_line_back_after_gap_and_rising() -> None:
    from northvaine.radar.timing import trade_changes

    new_line = _importer(
        ["2026-02", "2026-04", "2026-08"],
        {"68022100": ["2026-02", "2026-04"], "68029990": ["2026-08"]},
    )
    lines = [line for _, line in trade_changes(new_line.candidate)]
    assert any(line.startswith("It added a new product line (code 68029990") for line in lines)
    back = _importer(["2026-01", "2026-06"], {"68022100": ["2026-01", "2026-06"]})
    assert any(
        "came back to importing in 2026-06 after 4 months" in line
        for _, line in trade_changes(back.candidate)
    )
    rising = _importer(
        ["2026-02", "2026-06", "2026-07", "2026-08"],
        {"68022100": ["2026-02", "2026-06", "2026-07", "2026-08"]},
    )
    assert any(
        line.startswith("Its imports are rising") for _, line in trade_changes(rising.candidate)
    )
    steady = _importer(
        [f"2026-0{m}" for m in range(1, 9)], {"68022100": [f"2026-0{m}" for m in range(1, 9)]}
    )
    assert trade_changes(steady.candidate) == []  # every month, no change: no signal
    # and it moves the lead: a fresh new line is clear intent
    assert assess(_fit(new_line), date(2026, 10, 20), SPEC).intent >= 2
