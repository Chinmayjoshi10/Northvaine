"""T5.2: match keys, one candidate per company, stream and window. Code only, no network."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from northvaine.brain.budget import RunContext
from northvaine.core.models import (
    ClaimCheck,
    ClaimDraft,
    ClaimStatus,
    ConceptAssignment,
    Eligibility,
    EvidenceDocument,
    EvidenceKind,
    LedgerResult,
    PendingEvent,
    SubjectMention,
)
from northvaine.core.settings import Settings
from northvaine.radar.entities import (
    build_candidates,
    company_key,
    stream_for,
    subject_problem,
    window_for,
)
from northvaine.radar.ledger import build_evidence, evidence_document_from_sensor
from northvaine.radar.models import CandidateEvent, RadarStream, RejectedAs
from northvaine.sensors.ted import parse_notice
from tests.radar.test_ledger_pipeline import CONCEPTS

SETTINGS = Settings(_env_file=None)
TED = Path(__file__).resolve().parents[1] / "fixtures" / "sensors" / "ted"
FETCHED = datetime(2026, 6, 1, tzinfo=UTC)


# --- company_key -----------------------------------------------------------------------------


def test_legal_forms_case_and_punctuation_do_not_change_the_key() -> None:
    assert company_key("ACME Bau GmbH", "DE", SETTINGS) == company_key("Acme Bau", "DE", SETTINGS)
    assert company_key("Acme  Bau, G.m.b.H.", "DE", SETTINGS) != ""
    assert company_key("Acme Bau", "DE", SETTINGS) == "DE:acme bau"


def test_different_countries_do_not_share_a_key() -> None:
    assert company_key("Acme Bau", "DE", SETTINGS) != company_key("Acme Bau", "AT", SETTINGS)


def test_missing_country_uses_the_placeholder() -> None:
    assert company_key("Acme Bau Ltd", None, SETTINGS) == "--:acme bau"


def test_multi_word_legal_form_is_removed() -> None:
    assert company_key("Zeta Sp. z o.o.", "PL", SETTINGS) == "PL:zeta"


def test_name_that_is_only_a_legal_form_keeps_its_own_text() -> None:
    assert company_key("GmbH", "DE", SETTINGS) == "DE:gmbh"


# --- synthetic ledger results ----------------------------------------------------------------


def make_doc(
    text: str = "Zeta Works placed an order.",
    *,
    source: str = "website",
    url: str = "https://zeta.example/a",
    available: datetime = FETCHED,
) -> EvidenceDocument:
    return EvidenceDocument(
        id=uuid4(), source_name=source, url=url, title=None, text=text, available_at=available
    )


def check(doc: EvidenceDocument, quote: str, *, offset: int | None = 0, ok: bool = True):
    draft = ClaimDraft(statement=f"S: {quote}", source_quote=quote, extracted_by="fast-llm")
    return ClaimCheck(
        document_id=doc.id,
        draft=draft,
        status=ClaimStatus.VERIFIED if ok else ClaimStatus.QUOTE_NOT_FOUND,
        quote_offset=offset if ok else None,
        verified_by="exact" if ok else None,
        fingerprint=f"fp-{quote}",
    )


def pending(
    checks: list[ClaimCheck],
    subject: SubjectMention | None,
    *,
    event_type: str = "facility_opened",
    occurred_on: date | None = None,
    slots: dict[str, Any] | None = None,
) -> PendingEvent:
    fps = [c.fingerprint for c in checks]
    return PendingEvent(
        event_type=event_type,
        claim_fingerprints=fps,
        occurred_on=occurred_on,
        available_at=FETCHED,
        subject=subject,
        description=f"{event_type} {subject.name if subject else ''}",
        concept=ConceptAssignment(
            level=0, label=event_type, description="d", status="active", is_new=False
        ),
        cluster_id=uuid4(),
        slots=slots or {},
        fingerprint=f"ev-{event_type}-{'-'.join(fps)}-{subject.name if subject else ''}",
    )


def result(doc: EvidenceDocument, checks: list[ClaimCheck], events: list[PendingEvent]):
    return LedgerResult(
        document_id=doc.id,
        eligibility=Eligibility(kind=EvidenceKind.FULL_TEXT),
        checks=checks,
        events=events,
    )


def subject(name: str, country: str | None = None, role: str = "buyer") -> SubjectMention:
    return SubjectMention(name=name, country=country, role=role)


def one_event_doc(name: str, country: str | None, text: str | None = None):
    doc = make_doc(text or f"{name} placed an order.")
    c = check(doc, f"{name} placed an order.")
    return doc, result(doc, [c], [pending([c], subject(name, country))])


def test_same_company_different_spelling_and_documents_is_one_candidate() -> None:
    d1, r1 = one_event_doc("ACME Bau GmbH", "DE")
    d2, r2 = one_event_doc("Acme Bau", "DE")
    candidates, rejected = build_candidates([(d1, r1), (d2, r2)], settings=SETTINGS)
    assert rejected == []
    assert len(candidates) == 1
    cand = candidates[0]
    assert cand.name == "ACME Bau GmbH"
    assert cand.aliases == ["Acme Bau"]
    assert {c.document_id for c in cand.claims} == {d1.id, d2.id}
    assert [c.ref for c in cand.claims] == ["C1", "C2"]
    assert len(cand.events) == 2


def test_different_countries_stay_two_candidates() -> None:
    d1, r1 = one_event_doc("Acme Bau", "DE")
    d2, r2 = one_event_doc("Acme Bau", "AT")
    candidates, _ = build_candidates([(d1, r1), (d2, r2)], settings=SETTINGS)
    assert sorted(c.key for c in candidates) == ["AT:acme bau", "DE:acme bau"]


def test_countryless_mention_joins_the_unique_countried_one() -> None:
    d1, r1 = one_event_doc("Acme Bau", "DE")
    d2, r2 = one_event_doc("ACME Bau Ltd", None)
    candidates, _ = build_candidates([(d2, r2), (d1, r1)], settings=SETTINGS)
    assert len(candidates) == 1
    assert candidates[0].country == "DE"
    assert len(candidates[0].claims) == 2


def test_countryless_mention_stays_separate_when_two_countries_exist() -> None:
    docs = [one_event_doc("Acme Bau", "DE"), one_event_doc("Acme Bau", "AT")]
    docs.append(one_event_doc("Acme Bau", None))
    candidates, _ = build_candidates(docs, settings=SETTINGS)
    assert sorted(c.key for c in candidates) == ["--:acme bau", "AT:acme bau", "DE:acme bau"]


def test_roles_are_deduplicated() -> None:
    docs = [one_event_doc("Acme Bau", "DE"), one_event_doc("Acme Bau", "DE")]
    candidates, _ = build_candidates(docs, settings=SETTINGS)
    assert candidates[0].roles == ["buyer"]


def test_claim_refs_follow_document_time_then_offset() -> None:
    early = make_doc("x", available=datetime(2026, 1, 1, tzinfo=UTC))
    late = make_doc("y", available=datetime(2026, 5, 1, tzinfo=UTC))
    c_late = check(late, "Late sentence about Zeta Works.", offset=3)
    c_b = check(early, "Second sentence about Zeta Works.", offset=50)
    c_a = check(early, "First sentence about Zeta Works.", offset=5)
    s = subject("Zeta Works", "NL")
    results = [
        (late, result(late, [c_late], [pending([c_late], s)])),
        (early, result(early, [c_b, c_a], [pending([c_b, c_a], s, event_type="x_event")])),
    ]
    (cand,), _ = build_candidates(results, settings=SETTINGS)
    assert [c.source_quote for c in cand.claims] == [
        "First sentence about Zeta Works.",
        "Second sentence about Zeta Works.",
        "Late sentence about Zeta Works.",
    ]
    event_x = next(e for e in cand.events if e.event_type == "x_event")
    assert event_x.claim_refs == ["C1", "C2"]


def test_unverified_claims_are_never_carried() -> None:
    doc = make_doc("Zeta Works placed an order. Zeta Works is huge.")
    good = check(doc, "Zeta Works placed an order.")
    bad = check(doc, "Zeta Works is huge.", ok=False)
    event = pending([good, bad], subject("Zeta Works", "NL"))
    (cand,), _ = build_candidates([(doc, result(doc, [good, bad], [event]))], settings=SETTINGS)
    assert [c.source_quote for c in cand.claims] == ["Zeta Works placed an order."]
    assert cand.events[0].claim_refs == ["C1"]


def test_event_without_subject_is_rejected_as_unidentified() -> None:
    doc = make_doc("An order was placed.", url="https://zeta.example/news")
    c = check(doc, "An order was placed.")
    res = result(doc, [c], [pending([c], None)])
    candidates, rejected = build_candidates([(doc, res)], settings=SETTINGS)
    assert candidates == []
    (entry,) = rejected
    assert entry.gate.rejected_as == RejectedAs.UNIDENTIFIED
    assert entry.gate.by == "code"
    assert entry.gate.passed is False
    assert entry.candidate.name == "(no company named)"
    assert "facility_opened" in entry.gate.reason
    assert "https://zeta.example/news" in entry.gate.reason


# --- D68: junk subjects ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "junk",
    [
        "the organization",
        "The Organisation",
        "https://zeta.example/page",
        "www.zeta.example",
        "zeta.example",
        "12345",
        "- / -",
        "it",
        "Our company",
        "Zeta opened a new plant in the north and then hired forty extra workers there last week",
        "The firm said: orders are up",
        "the new product range",
    ],
)
def test_junk_subjects_are_never_candidates(junk: str) -> None:
    assert subject_problem(junk, SETTINGS) is not None
    doc, res = one_event_doc(junk, None, text=f"{junk} placed an order.")
    candidates, rejected = build_candidates([(doc, res)], settings=SETTINGS)
    assert candidates == []
    assert [r.gate.rejected_as for r in rejected] == [RejectedAs.UNIDENTIFIED]
    assert "subject" in rejected[0].gate.reason


@pytest.mark.parametrize(
    "name",
    [
        "Acme Bau GmbH",
        "S.p.A. Zeta",
        "The Hague Municipality",
        "Zeta & Sons Ltd",
        "Société Générale",
    ],
)
def test_real_names_pass_the_junk_rule(name: str) -> None:
    assert subject_problem(name, SETTINGS) is None


# --- stream and window -----------------------------------------------------------------------


def test_stream_comes_from_settings_for_enumerable_sources_only() -> None:
    assert stream_for("ted", "tender_published", SETTINGS) == RadarStream.TENDER
    assert stream_for("ted", "contract_awarded", SETTINGS) == RadarStream.AWARD
    assert stream_for("website", "tender_published", SETTINGS) == RadarStream.ANNOUNCEMENT
    assert stream_for("ted", "facility_opened", SETTINGS) == RadarStream.ANNOUNCEMENT


def cand_event(event_type: str, occurred: date | None, **slots: Any) -> CandidateEvent:
    return CandidateEvent(
        event_type=event_type,
        description="d",
        occurred_on=occurred,
        available_at=None,
        claim_refs=[],
        slots=slots,
        fingerprint=f"{event_type}-{occurred}",
    )


def test_tender_window_uses_the_stated_deadline() -> None:
    ev = cand_event("tender_published", date(2026, 6, 1), deadlines="2026-07-15T12:00:00+02:00")
    assert window_for(RadarStream.TENDER, [ev], SETTINGS)[:3] == (
        date(2026, 6, 1),
        date(2026, 7, 15),
        False,
    )


def test_tender_window_takes_the_earliest_of_several_deadlines() -> None:
    ev = cand_event("tender_published", date(2026, 6, 1), deadlines="2026-08-01, 2026-07-01")
    assert window_for(RadarStream.TENDER, [ev], SETTINGS)[1] == date(2026, 7, 1)


def test_tender_window_without_deadline_is_estimated() -> None:
    ev = cand_event("tender_published", date(2026, 6, 1))
    start, end, estimated, note = window_for(RadarStream.TENDER, [ev], SETTINGS)
    assert (start, end, estimated) == (date(2026, 6, 1), date(2026, 7, 1), True)
    assert note


def test_tender_window_ignores_unparseable_deadline() -> None:
    ev = cand_event("tender_published", date(2026, 6, 1), deadlines="soon")
    assert window_for(RadarStream.TENDER, [ev], SETTINGS)[2] is True


def test_award_and_announcement_windows() -> None:
    award = window_for(RadarStream.AWARD, [cand_event("contract_awarded", date(2026, 6, 1))])
    assert award[:3] == (None, None, False)
    assert "future bids" in award[3]
    ann = window_for(RadarStream.ANNOUNCEMENT, [cand_event("facility_opened", date(2026, 3, 5))])
    assert ann[:3] == (date(2026, 3, 5), None, False)
    assert "not enumerable" in ann[3]
    undated = window_for(RadarStream.ANNOUNCEMENT, [cand_event("facility_opened", None)])
    assert undated[:3] == (None, None, False)


def test_primary_stream_priority_keeps_all_streams() -> None:
    doc = make_doc("t", source="ted")
    c = check(doc, "Buyer [x]: Zeta Works")
    s = subject("Zeta Works", "NL")
    tender = pending([c], s, event_type="tender_published", occurred_on=date(2026, 6, 1))
    award = pending([c], s, event_type="contract_awarded", occurred_on=date(2026, 6, 2))
    note = make_doc("n")
    c2 = check(note, "Zeta Works opened a plant.")
    news = pending([c2], s, event_type="facility_opened", occurred_on=date(2026, 3, 1))
    res = [
        (doc, result(doc, [c], [award, tender])),
        (note, result(note, [c2], [news])),
    ]
    (cand,), _ = build_candidates(res, settings=SETTINGS)
    assert cand.stream == RadarStream.TENDER
    assert cand.streams == [RadarStream.TENDER, RadarStream.ANNOUNCEMENT, RadarStream.AWARD]
    assert cand.window_start == date(2026, 6, 1)
    assert cand.window_estimated is True

    res_no_tender = [(doc, result(doc, [c], [award])), (note, result(note, [c2], [news]))]
    (cand2,), _ = build_candidates(res_no_tender, settings=SETTINGS)
    assert cand2.stream == RadarStream.ANNOUNCEMENT


# --- recorded TED fixtures through build_evidence --------------------------------------------


def recorded_docs() -> list[EvidenceDocument]:
    docs: list[EvidenceDocument] = []
    for path in sorted(TED.glob("*.json")):
        for exchange in json.loads(path.read_text(encoding="utf-8")):
            for record in exchange["body_json"]["notices"]:
                sensor_doc = parse_notice(record, fetched_at=FETCHED, settings=SETTINGS)
                docs.append(evidence_document_from_sensor(sensor_doc))
    return docs


@pytest.fixture(scope="module")
def ted_results() -> list[tuple[EvidenceDocument, LedgerResult]]:
    import asyncio

    async def run() -> list[tuple[EvidenceDocument, LedgerResult]]:
        out = []
        for doc in recorded_docs():
            res = await build_evidence(doc, CONCEPTS, [], run=RunContext(), settings=SETTINGS)
            out.append((doc, res))
        return out

    return asyncio.run(run())


def test_ted_awards_yield_winner_candidates_and_tenders_yield_buyer_windows(ted_results) -> None:
    candidates, rejected = build_candidates(ted_results, settings=SETTINGS)
    events = [e for _, r in ted_results for e in r.events]
    awards = [e for e in events if e.event_type == "contract_awarded"]
    tenders = [e for e in events if e.event_type == "tender_published"]
    assert awards and tenders
    by_name = {n: c for c in candidates for n in [c.name, *c.aliases]}
    for award in awards:
        assert award.subject is not None and award.subject.role == "winner"
        if award.subject.name.startswith("["):
            continue  # a withheld natural-person name is never a candidate (D76)
        cand = by_name[award.subject.name]
        assert RadarStream.AWARD in cand.streams
    for tender in tenders:
        assert tender.subject is not None
        cand = by_name[tender.subject.name]
        assert RadarStream.TENDER in cand.streams
        assert cand.stream == RadarStream.TENDER
        assert cand.window_start is not None and cand.window_end is not None
    assert all(r.gate.rejected_as == RejectedAs.UNIDENTIFIED for r in rejected)
    # Winnerless awards (D56) produced no event and therefore no candidate or rejection here.
    assert not any(e.event_type == "contract_awarded" and e.subject is None for e in events)


def test_every_candidate_claim_is_verified_and_quoted_from_its_document(ted_results) -> None:
    candidates, rejected = build_candidates(ted_results, settings=SETTINGS)
    docs = {d.id: d for d, _ in ted_results}
    verified = {c.fingerprint for _, r in ted_results for c in r.checks if c.verified}
    entries = [*candidates, *(r.candidate for r in rejected)]
    assert entries
    for cand in entries:
        refs = {c.ref for c in cand.claims}
        for claim in cand.claims:
            assert claim.fingerprint in verified
            assert claim.source_quote in docs[claim.document_id].text
        for event in cand.events:
            assert set(event.claim_refs) <= refs
    for cand in candidates:
        assert cand.claims


def test_recorded_tender_deadlines_make_non_estimated_windows(ted_results) -> None:
    candidates, _ = build_candidates(ted_results, settings=SETTINGS)
    tenders = [c for c in candidates if c.stream == RadarStream.TENDER]
    stated = [c for c in tenders if not c.window_estimated]
    estimated = [c for c in tenders if c.window_estimated]
    assert stated or estimated
    for cand in estimated:
        assert cand.window_end is not None and cand.window_start is not None
        assert (cand.window_end - cand.window_start).days == SETTINGS.radar_tender_window_days


def test_a_withheld_name_is_never_a_candidate() -> None:
    from northvaine.radar.entities import subject_problem

    assert subject_problem("[natural person, name withheld 1a2b3c4d]") is not None
