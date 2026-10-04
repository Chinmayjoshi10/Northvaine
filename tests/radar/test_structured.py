"""T4.3: code-only evidence from structured records (TED). No LLM is ever called."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest

from northvaine.brain import llm
from northvaine.core.models import EvidenceDocument
from northvaine.core.settings import Settings
from northvaine.radar.ledger import evidence_document_from_sensor
from northvaine.radar.structured import structured_evidence
from northvaine.sensors.ted import parse_notice

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "sensors" / "ted"
FETCHED = datetime(2026, 6, 1, tzinfo=UTC)
SETTINGS = Settings(_env_file=None)


class FailingClient:
    """Any attribute access means a model call was attempted."""

    def __getattr__(self, name: str) -> Any:
        raise AssertionError(f"structured evidence must not call an LLM ({name})")


def recorded_records() -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in sorted(FIXTURES.glob("*.json")):
        for exchange in json.loads(path.read_text(encoding="utf-8")):
            records.extend(exchange["body_json"]["notices"])
    return records


def doc_for(record: dict[str, Any]) -> EvidenceDocument:
    sensor_doc = parse_notice(record, fetched_at=FETCHED, settings=SETTINGS)
    return evidence_document_from_sensor(sensor_doc)


def record(number: str = "100-2026", **kw: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "publication-number": number,
        "notice-type": "cn-standard",
        "notice-version": 1,
        "procedure-identifier": f"proc-{number}",
        "publication-date": "2026-06-01+02:00",
        "buyer-name": {"eng": ["Stadt A"]},
        "buyer-country": ["DEU"],
        "classification-cpv": ["12345678"],
        "deadline-receipt-request": ["2026-07-01T12:00:00+02:00"],
    }
    base.update(kw)
    return base


@pytest.fixture(autouse=True)
def _defaults(clean_settings: None) -> None:
    return None


def test_the_recorded_corpus_is_not_empty() -> None:
    assert len(recorded_records()) > 20


def test_every_recorded_notice_yields_exact_line_quotes_and_valid_indices() -> None:
    kinds: set[str] = set()
    with llm.client_override(FailingClient()):
        for rec in recorded_records():
            doc = doc_for(rec)
            result = structured_evidence(doc)
            assert result is not None
            claims, events = result
            lines = doc.text.split("\n")
            for claim in claims:
                assert claim.source_quote in lines
                assert claim.extracted_by == "code"
                assert claim.statement and claim.statement != claim.source_quote
            for event in events:
                kinds.add(event.event_type)
                assert event.claim_indices
                assert len(set(event.claim_indices)) == len(event.claim_indices)
                assert all(0 <= i < len(claims) for i in event.claim_indices)
                assert event.group_key == doc.group_key
    assert "tender_published" in kinds


def test_tender_event_is_dated_by_publication_with_buyer_subject() -> None:
    doc = doc_for(record())
    result = structured_evidence(doc)
    assert result is not None
    claims, events = result
    (event,) = events
    assert event.event_type == "tender_published"
    assert event.occurred_on == date(2026, 6, 1)
    assert event.subject is not None
    assert (event.subject.name, event.subject.country, event.subject.role) == (
        "Stadt A",
        "DE",
        "buyer",
    )
    assert event.slots["cpv_codes"] == "12345678"
    assert event.slots["buyer_names"] == "Stadt A"
    quotes = [claims[i].source_quote for i in event.claim_indices]
    assert "Deadline: 2026-07-01T12:00:00+02:00" in quotes
    assert event.group_key == "proc-100-2026"


def test_award_makes_one_event_per_winner_dated_by_decision() -> None:
    rec = record(
        **{
            "notice-type": "can-standard",
            "winner-name": {"eng": ["Firma B", "Firma C"]},
            "winner-country": ["DEU", "AUT"],
            "winner-decision-date": ["2026-05-29+02:00"],
            "total-value": 1500.5,
        }
    )
    result = structured_evidence(doc_for(rec))
    assert result is not None
    claims, events = result
    assert [e.event_type for e in events] == ["contract_awarded", "contract_awarded"]
    assert [e.subject.name for e in events if e.subject] == ["Firma B", "Firma C"]
    assert [e.subject.country for e in events if e.subject] == ["DE", "AT"]
    assert {e.occurred_on for e in events} == {date(2026, 5, 29)}
    assert events[0].slots["value"] == "1500.50"
    assert events[0].slots["winner_name"] == "Firma B"
    quotes = {claims[i].source_quote for i in events[0].claim_indices}
    assert "Winner decision date: 2026-05-29+02:00" in quotes


def test_award_without_decision_date_uses_publication() -> None:
    rec = record(**{"notice-type": "can-standard", "winner-name": {"eng": ["Firma B"]}})
    result = structured_evidence(doc_for(rec))
    assert result is not None
    assert [e.occurred_on for e in result[1]] == [date(2026, 6, 1)]


def test_multi_language_buyer_quotes_the_whole_line() -> None:
    rec = record(**{"buyer-name": {"eng": ["Town"], "deu": ["Stadt"]}})
    doc = doc_for(rec)
    result = structured_evidence(doc)
    assert result is not None
    quotes = [c.source_quote for c in result[0] if c.source_quote.startswith("Buyer [")]
    assert len(quotes) == 1 and quotes[0] in doc.text.split("\n")


def test_not_structured_source_gives_none() -> None:
    doc = doc_for(record()).model_copy(update={"source_name": "website"})
    assert structured_evidence(doc) is None
    assert structured_evidence(doc.model_copy(update={"source_name": "tavily"})) is None


def test_unknown_schema_version_gives_none() -> None:
    doc = doc_for(record())
    assert (
        structured_evidence(doc.model_copy(update={"meta": {**doc.meta, "schema_ver": 2}})) is None
    )
    no_ver = {k: v for k, v in doc.meta.items() if k != "schema_ver"}
    assert structured_evidence(doc.model_copy(update={"meta": no_ver})) is None


def test_unknown_country_code_is_dropped_not_guessed() -> None:
    result = structured_evidence(doc_for(record(**{"buyer-country": ["ZZZ"]})))
    assert result is not None
    subject = result[1][0].subject
    assert subject is not None and subject.country is None


def test_the_notice_title_is_a_claim_english_first() -> None:
    titles = {"deu": "Neugestaltung Marktplatz", "eng": "Redesign of the market square"}
    doc = doc_for(record(**{"notice-title": titles}))
    result = structured_evidence(doc)
    assert result is not None
    claims, (event,) = result
    quotes = [claims[i].source_quote for i in event.claim_indices]
    assert "Title [eng]: Redesign of the market square" in quotes
    assert not any(q.startswith("Title [deu]") for q in quotes)  # one title, not every language
