"""The trade stream (D102): an importer of record from official import records is a proven
buyer, ranked below a stated purchase and above a project need, and contacted only after a
check of what it sells. Synthetic candidates with invented names; no network, no model."""

from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import uuid4

from northvaine.api.views import chain
from northvaine.core.models import EvidenceKind
from northvaine.core.settings import Settings
from northvaine.radar import brief
from northvaine.radar.account import account_role, evidence_level
from northvaine.radar.entities import stream_for, window_for
from northvaine.radar.models import (
    Candidate,
    CandidateClaim,
    CandidateEvent,
    FitEvidence,
    GateDecision,
    RadarStream,
    SkepticFinding,
)

NOW = datetime(2026, 10, 14, 9, 0, tzinfo=UTC)
SETTINGS = Settings(_env_file=None)
UNKNOWN = SkepticFinding(stance="unknown", against=[], open_questions=["Who supplies it now?"])


def claim(ref: str, quote: str, kind: EvidenceKind = EvidenceKind.STRUCTURED) -> CandidateClaim:
    return CandidateClaim(
        ref=ref,
        fingerprint=f"fp-{ref}",
        document_id=uuid4(),
        statement=f"Statement for {ref}.",
        source_quote=quote,
        source_name="hmrc",
        url="https://api.uktradeinfo.com/Trader(1)",
        available_at=NOW,
        evidence_kind=kind,
        verified_by="code",
        upgraded_from=None,
    )


def importer(name: str, *, new: bool) -> Candidate:
    history = (
        "New importer: first recorded importing these codes in 2026-05, none recorded in 2025"
        if new
        else "Also recorded importing these codes in 2025"
    )
    claims = [
        claim("C1", f"Importer: {name}"),
        claim("C2", "Postcode: ZZ1 1ZZ"),
        claim("C3", "Commodity 12345678 (Test goods): imported in 2026-05, 2026-07"),
        claim("C4", history),
    ]
    first = "2026-05"
    return Candidate(
        key=name.lower(),
        name=name,
        country="GB",
        aliases=[],
        roles=["importer"],
        stream=RadarStream.TRADE,
        streams=[RadarStream.TRADE],
        events=[
            CandidateEvent(
                event_type="imports_recorded",
                description=f"{name} imported test goods",
                occurred_on=date(2026, 7, 1),
                available_at=NOW,
                claim_refs=["C1", "C2", "C3", "C4"],
                slots={
                    "codes": "12345678",
                    "first_month": first,
                    "last_month": "2026-07",
                    "months_active": 2,
                    "new_this_year": new,
                },
                fingerprint=f"ev-{name}",
            )
        ],
        claims=claims,
        window_start=date(2026, 5, 1),
        window_end=None,
        window_estimated=False,
        window_note="",
    )


def gate() -> GateDecision:
    return GateDecision(
        passed=True,
        rejected_as=None,
        by="llm",
        reason="an importer of the client's product",
        direct_buyer=True,
        buyer_reason="imports the goods itself",
        demand_reason="it imports this product every month",
        suggested_action="ask who supplies it now",
        cited_refs=["C1"],
    )


def test_trade_stream_and_window() -> None:
    assert stream_for("hmrc", "imports_recorded", SETTINGS) == RadarStream.TRADE
    assert stream_for("website", "imports_recorded", SETTINGS) == RadarStream.ANNOUNCEMENT
    c = importer("Example Imports Ltd", new=True)
    start, end, estimated, note = window_for(RadarStream.TRADE, c.events, SETTINGS)
    assert (start, end, estimated) == (date(2026, 5, 1), None, False)
    assert "no purchase window" in note


def test_role_and_level() -> None:
    c = importer("Example Imports Ltd", new=False)
    assert account_role(c, None) == "importer_of_record"
    assert evidence_level("stated", "importer_of_record", True) == "proven_buyer"
    assert evidence_level("inferred", "importer_of_record", True) == "no_evidence"


def test_ranked_as_proven_buyer_new_importers_first() -> None:
    old = importer("Old Imports Ltd", new=False)
    new = importer("New Imports Ltd", new=True)
    entries = brief.rank(
        [(old, gate(), UNKNOWN), (new, gate(), UNKNOWN)],
        as_of=NOW,
        settings=SETTINGS,
        terms=["unrelated word"],
    )
    assert [e.candidate.name for e in entries] == ["New Imports Ltd", "Old Imports Ltd"]
    top = entries[0]
    assert top.requirement == "stated" and top.requirement_ref == "C3"
    assert top.evidence_level == "proven_buyer"
    assert top.account_role == "importer_of_record"
    assert any("official import records" in r for r in top.rank_reasons)
    assert any("started importing this year" in r for r in top.rank_reasons)
    assert brief.action_status(top) == "qualify first"
    assert "check what it sells" in brief.caution(top)


def test_contact_now_only_after_its_own_site_names_the_product() -> None:
    (entry,) = brief.rank(
        [(importer("Fit Imports Ltd", new=True), gate(), UNKNOWN)], as_of=NOW, settings=SETTINGS
    )
    fit = FitEvidence(
        level="stated",
        quote="We stock test goods for trade customers.",
        url="https://fit-imports.example/products",
        term="test goods",
        fingerprint="fit-1",
    )
    fitted = entry.model_copy(update={"company_fit": [fit], "fit_level": "stated"})
    assert brief.action_status(fitted) == "contact now"


def test_chain_reads_the_record_lines() -> None:
    (entry,) = brief.rank(
        [(importer("Chain Imports Ltd", new=True), gate(), UNKNOWN)], as_of=NOW, settings=SETTINGS
    )
    links = chain(entry)
    assert [link.slot for link in links] == ["importer", "product", "history", "buyer"]
    assert [link.state for link in links] == ["stated", "stated", "stated", "unknown"]
    assert links[1].label == "Commodity 12345678 (Test goods)"
    assert links[2].label == "new importer this year"


def test_a_trade_query_keeps_its_own_cap() -> None:
    from northvaine.core.models import EventType
    from northvaine.radar.discover import focus_queries
    from northvaine.sensors.base import SensorQuery

    trade = SensorQuery(kinds=[EventType.IMPORTS_RECORDED], codes=["hs:123456"], max_results=20)
    award = SensorQuery(kinds=[EventType.CONTRACT_AWARDED], codes=["cpv:12345678"], max_results=20)
    out = focus_queries({"hmrc": [trade], "fts": [award]}, SETTINGS)
    assert out["hmrc"][0].max_results == 20
    assert out["fts"][0].max_results == SETTINGS.radar_enumerable_max_results


def test_proven_buyers_are_gated_after_open_tenders_and_before_the_rest() -> None:
    from northvaine.radar.run import _gate_order

    trade = importer("Gate Imports Ltd", new=True)
    many = trade.model_copy(
        update={
            "key": "award",
            "stream": RadarStream.AWARD,
            "claims": trade.claims * 3,
        }
    )
    open_tender = trade.model_copy(
        update={"key": "tender", "stream": RadarStream.TENDER, "window_end": date(2026, 11, 1)}
    )
    order = _gate_order([many, trade, open_tender], date(2026, 10, 14))
    assert [c.key for c in order] == ["tender", "gate imports ltd", "award"]


def test_what_names_the_imported_goods() -> None:
    what = brief._what(importer("What Imports Ltd", new=True))
    assert what == r"imports 12345678 \(Test goods\)"  # escaped for the Markdown tables


def test_the_app_gets_names_without_markdown_escapes() -> None:
    from northvaine.api.views import _plain_name, _plain_what

    c = importer("K & H (Example) Ltd", new=True)
    assert _plain_name(c) == "K & H (Example) Ltd"
    assert _plain_what(c) == "imports 12345678 (Test goods)"


def test_the_app_shows_the_register_spelling_when_there_is_one() -> None:
    from northvaine.api.views import _plain_name
    from northvaine.radar.models import RegisterFacts

    c = importer("ACME LIM ITED", new=True)
    assert _plain_name(c) == "ACME LIM ITED"
    facts = RegisterFacts(number="1", name="ACME LIMITED", status="active")
    c = c.model_copy(update={"company_register": facts})
    assert _plain_name(c) == "ACME LIMITED"
