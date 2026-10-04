"""T4.5: grounding, descriptions, build_evidence and process_document, with fake clients.

No network, no database. The recording fake logs every chat and embed call in order.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest

from northvaine.brain import llm as llm_module
from northvaine.brain.budget import RunContext
from northvaine.core import ledger as store
from northvaine.core.models import (
    ClaimCheck,
    ClaimDraft,
    ClaimStatus,
    ClusterCandidate,
    ConceptStatus,
    EventConceptRow,
    EventDraft,
    EvidenceDocument,
    EvidenceKind,
    SubjectMention,
)
from northvaine.core.settings import Settings
from northvaine.radar.ledger import (
    build_evidence,
    describe_event,
    evidence_document_from_sensor,
    ground_event,
    process_document,
)
from northvaine.radar.quote_check import find_quote
from northvaine.sensors.tavily import parse_result
from northvaine.sensors.ted import parse_notice

FAST = "nvidia/Nemotron-3_5-Lightning"
EMBED = "Qwen/Qwen3-Embedding-8B"
SETTINGS = Settings(_env_file=None)
AVAILABLE = datetime(2026, 6, 2, tzinfo=UTC)

TEXT = (
    "Harbourside Works opened a new plant in Rotterdam on 2026-03-05.\n"
    "The company employs 240 staff across three sites.\n"
    "The cafeteria serves lunch daily."
)
Q_OPEN = "Harbourside Works opened a new plant in Rotterdam on 2026-03-05."
Q_STAFF = "The company employs 240 staff across three sites."
Q_MISSING = "This sentence is nowhere in the document at all, honestly."


# --- fakes -----------------------------------------------------------------------------------


class Recorder:
    """A client that logs ('chat' | 'embed', body) in call order."""

    def __init__(self, chat_replies: list[Any] | None = None) -> None:
        self.log: list[tuple[str, dict[str, Any]]] = []
        self.replies = list(chat_replies or [])
        self.vectors: list[list[float]] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._chat))
        self.embeddings = SimpleNamespace(create=self._embed)

    async def _chat(self, **body: Any) -> Any:
        self.log.append(("chat", body))
        content = json.dumps(self.replies.pop(0))
        return SimpleNamespace(
            choices=[
                SimpleNamespace(message=SimpleNamespace(content=content), finish_reason="stop")
            ],
            usage=SimpleNamespace(prompt_tokens=50, completion_tokens=10, total_tokens=60),
        )

    async def _embed(self, **body: Any) -> Any:
        self.log.append(("embed", body))
        vector = self.vectors.pop(0) if self.vectors else unit(0)
        return SimpleNamespace(
            data=[SimpleNamespace(embedding=vector)],
            usage=SimpleNamespace(prompt_tokens=8, total_tokens=8),
        )

    @property
    def kinds(self) -> list[str]:
        return [kind for kind, _ in self.log]

    def prompt(self, position: int) -> str:
        return "\n".join(m["content"] for m in self.log[position][1]["messages"])


def unit(index: int) -> list[float]:
    vector = [0.0] * llm_module.EMBED_DIM_EXPECTED
    vector[index] = 1.0
    return vector


class Forbidden:
    """Any attribute access means a model call was attempted."""

    def __getattr__(self, name: str) -> Any:
        raise AssertionError(f"no model call allowed here ({name})")


@pytest.fixture(autouse=True)
def _configured(monkeypatch: pytest.MonkeyPatch, clean_settings: None) -> None:
    settings = Settings(
        _env_file=None,
        model_fast=FAST,
        model_embed=EMBED,
        daily_budget_usd=Decimal("10"),
        total_budget_usd=Decimal("20"),
        run_budget_usd=Decimal("5"),
        max_call_cost_usd=Decimal("1"),
    )
    monkeypatch.setattr(llm_module, "get_settings", lambda: settings)
    monkeypatch.setattr(llm_module.budget_module, "get_settings", lambda: settings)


def concept(label: str, *, parent: UUID | None = None, embedding: Any = None) -> EventConceptRow:
    return EventConceptRow(
        id=uuid4(),
        parent_id=parent,
        level=0 if parent is None else 1,
        label=label,
        description=f"description of {label}",
        embedding=embedding,
        status=ConceptStatus.ACTIVE,
        merged_into=None,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


CONCEPTS = [
    concept("facility_opened"),
    concept("tender_published"),
    concept("contract_awarded"),
    concept("reorder_due"),
]


def website_doc(text: str = TEXT) -> EvidenceDocument:
    return EvidenceDocument(
        id=uuid4(),
        source_name="website",
        url="https://harbourside.example/news",
        title="News",
        text=text,
        available_at=AVAILABLE,
    )


def claim(quote: str, statement: str = "A statement.", **kw: Any) -> dict[str, Any]:
    return {"statement": statement, "source_quote": quote, **kw}


def event(**kw: Any) -> dict[str, Any]:
    base: dict[str, Any] = {"event_type": "facility_opened", "claim_indices": [0], "slots": []}
    base.update(kw)
    return base


def verdicts(*flags: bool) -> dict[str, Any]:
    return {"verdicts": [{"index": i, "supported": f} for i, f in enumerate(flags)]}


def check(quote: str, status: ClaimStatus = ClaimStatus.VERIFIED, statement: str = "S.") -> Any:
    ok = status == ClaimStatus.VERIFIED
    return ClaimCheck(
        document_id=uuid4(),
        draft=ClaimDraft(statement=statement, source_quote=quote, extracted_by="t"),
        status=status,
        quote_offset=0 if ok else None,
        verified_by="code" if ok else None,
        fingerprint=f"fp-{quote[:12]}-{status.value}",
    )


# --- ground_event ----------------------------------------------------------------------------


def test_ground_event_drops_every_field_absent_from_the_verified_quotes() -> None:
    checks = [
        check(Q_OPEN),
        check(Q_STAFF, ClaimStatus.UNSUPPORTED),
        check(
            "Zyxwv Corporation moved its entire head office to Narnia, 2031.",
            ClaimStatus.QUOTE_NOT_FOUND,
        ),
    ]
    draft = EventDraft(
        event_type="facility_opened",
        claim_indices=[0, 1, 2, 9],
        subject=SubjectMention(name="Harbourside Works", country="DE", role="operator"),
        date_text="2026-03-05",
        occurred_on=date(2026, 3, 5),
        slots={"city": "Rotterdam", "ghost": "Narnia", "headcount": "240", "n": 3},
    )
    got = ground_event(draft, checks)
    assert got is not None
    assert got.claim_indices == [0]
    assert got.occurred_on == date(2026, 3, 5) and got.date_text == "2026-03-05"
    assert got.subject is not None and got.subject.name == "Harbourside Works"
    assert got.subject.country is None  # neither DE, DEU nor Germany is in the quote
    # "240" is only in the unsupported claim's quote; "Narnia" only in the rejected one.
    assert got.slots == {"city": "Rotterdam", "n": 3}


def test_ground_event_drops_date_and_subject_not_in_the_quote() -> None:
    draft = EventDraft(
        event_type="facility_opened",
        claim_indices=[0],
        subject=SubjectMention(name="Someone Else Ltd", country=None, role="operator"),
        date_text="2026-04-01",
        occurred_on=date(2026, 4, 1),
        group_key="g",
    )
    got = ground_event(draft, [check(Q_OPEN)])
    assert got is not None
    assert got.subject is None and got.occurred_on is None and got.date_text is None
    assert got.group_key == "g"


def test_ground_event_keeps_a_country_found_by_code_or_name() -> None:
    subject = SubjectMention(name="Acme", country="DE", role="buyer")
    base = {"event_type": "facility_opened", "claim_indices": [0], "subject": subject}
    by_name = ground_event(EventDraft(**base), [check("Acme is a company based in Germany.")])
    by_code = ground_event(EventDraft(**base), [check("Acme [DE] is a company that builds.")])
    by_iso3 = ground_event(EventDraft(**base), [check("Buyer country: Acme DEU")])
    inside_word = ground_event(EventDraft(**base), [check("Acme made a decision to build.")])
    assert by_name and by_name.subject and by_name.subject.country == "DE"
    assert by_code and by_code.subject and by_code.subject.country == "DE"
    assert by_iso3 and by_iso3.subject and by_iso3.subject.country == "DE"
    assert inside_word and inside_word.subject and inside_word.subject.country is None


def test_ground_event_none_without_a_verified_claim() -> None:
    draft = EventDraft(event_type="facility_opened", claim_indices=[0])
    assert ground_event(draft, [check(Q_OPEN, ClaimStatus.UNSUPPORTED)]) is None
    assert ground_event(draft, []) is None


# --- describe_event --------------------------------------------------------------------------


def test_describe_event_is_composed_from_verified_statements() -> None:
    subject = SubjectMention(name="Harbourside Works", country=None, role="operator")
    got = describe_event("facility_opened", subject, ["It opened.", "It opened.", " Staff: 240. "])
    assert got == "facility opened - Harbourside Works. It opened. Staff: 240."
    assert describe_event("tender_published", None, []) == "tender published."


# --- build_evidence: leads and structured ----------------------------------------------------

TED_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "sensors"


def ted_doc(
    number: str = "100-2026", procedure: str = "proc-100", buyer: str = "Stadt A"
) -> EvidenceDocument:
    record = {
        "publication-number": number,
        "notice-type": "cn-standard",
        "notice-version": 1,
        "procedure-identifier": procedure,
        "publication-date": "2026-06-01+02:00",
        "buyer-name": {"eng": [buyer]},
        "buyer-country": ["DEU"],
        "classification-cpv": ["12345678"],
        "deadline-receipt-request": ["2026-07-01T12:00:00+02:00"],
    }
    sensor_doc = parse_notice(record, fetched_at=AVAILABLE, settings=SETTINGS)
    return evidence_document_from_sensor(sensor_doc).model_copy(update={"available_at": AVAILABLE})


async def test_a_lead_makes_no_claims_and_no_llm_call() -> None:
    text_kind = {"text_kind": "snippet"}
    doc = EvidenceDocument(
        id=uuid4(), source_name="tavily", url="https://x.example", text="a snippet", meta=text_kind
    )
    with llm_module.client_override(Forbidden()):
        result = await build_evidence(doc, CONCEPTS, [], run=RunContext(), settings=SETTINGS)
    assert result.eligibility.kind == EvidenceKind.LEAD and result.eligibility.reason
    assert result.checks == [] and result.events == [] and result.llm_calls == 0


async def test_recorded_tavily_snippets_are_leads() -> None:
    results = []
    for path in sorted((TED_DIR / "tavily").glob("*.json")):
        for exchange in json.loads(path.read_text(encoding="utf-8")):
            results.extend((exchange.get("body_json") or {}).get("results", []))
    snippets = [
        parse_result(r, fetched_at=AVAILABLE)
        for r in results
        if parse_result(r, fetched_at=AVAILABLE).meta.get("text_kind") == "snippet"
    ]
    assert snippets
    with llm_module.client_override(Forbidden()):
        for sensor_doc in snippets:
            doc = evidence_document_from_sensor(sensor_doc)
            result = await build_evidence(doc, CONCEPTS, [], run=RunContext(), settings=SETTINGS)
            assert result.eligibility.kind == EvidenceKind.LEAD and result.llm_calls == 0


async def test_structured_document_is_code_only() -> None:
    doc = ted_doc()
    with llm_module.client_override(Forbidden()):
        result = await build_evidence(doc, CONCEPTS, [], run=RunContext(), settings=SETTINGS)
    assert result.eligibility.kind == EvidenceKind.STRUCTURED and result.llm_calls == 0
    assert result.checks and all(c.verified and c.verified_by == "code" for c in result.checks)
    (event,) = result.events
    assert event.event_type == "tender_published" and event.embedding is None
    parent = CONCEPTS[1]
    assert event.concept.concept_id == parent.id and event.concept.level == 0
    assert event.available_at == AVAILABLE
    assert event.occurred_on == date(2026, 6, 1)
    assert event.slots["subject_key"] == "stadt a" and event.slots["group_key"] == "proc-100"
    assert event.subject is not None and event.subject.name == "Stadt A"
    # Every event field is inside a verified quote of that event (D50).
    quotes = [
        c.draft.source_quote for c in result.checks if c.fingerprint in event.claim_fingerprints
    ]
    assert any("Stadt A" in q for q in quotes)
    assert event.fingerprint and event.claim_fingerprints


async def test_two_versions_of_one_procedure_share_a_cluster() -> None:
    first = await build_evidence(
        ted_doc("100-2026"), CONCEPTS, [], run=RunContext(), settings=SETTINGS
    )
    seen = [
        ClusterCandidate(
            cluster_id=e.cluster_id,
            event_type=e.event_type,
            occurred_on=e.occurred_on,
            subject_key=e.slots.get("subject_key"),
            group_key=e.slots.get("group_key"),
        )
        for e in first.events
    ]
    again = await build_evidence(
        ted_doc("101-2026"), CONCEPTS, seen, run=RunContext(), settings=SETTINGS
    )
    other = await build_evidence(
        ted_doc("102-2026", "proc-other", "Stadt B"),
        CONCEPTS,
        seen,
        run=RunContext(),
        settings=SETTINGS,
    )
    assert again.events[0].cluster_id == first.events[0].cluster_id
    assert other.events[0].cluster_id != first.events[0].cluster_id


# --- build_evidence: full text ---------------------------------------------------------------


def full_text_replies() -> list[dict[str, Any]]:
    extraction = {
        "claims": [
            claim(
                Q_OPEN,
                "Harbourside Works opened a plant in Rotterdam.",
                subject_name="Harbourside Works",
                subject_country="DE",
                subject_role="operator",
            ),
            claim(Q_STAFF, "Harbourside Works employs 240 people."),
            claim(Q_MISSING, "An invented fact."),
        ],
        "events": [
            event(
                claim_indices=[0, 1],
                subject_name="Harbourside Works",
                date_text="2026-03-05",
                group_hint="harbourside-plant",
                slots=[{"name": "city", "value": "Rotterdam"}, {"name": "ghost", "value": "Zyxwv"}],
                concept_label="new_plant",
                concept_hint="A new production plant",
            ),
            event(claim_indices=[2]),  # only the invented claim: dropped
        ],
    }
    return [extraction, verdicts(True, True)]


async def test_full_text_pipeline_orders_calls_and_grounds_every_field() -> None:
    doc = website_doc()
    client = Recorder(full_text_replies())
    client.vectors = [unit(3)]
    with llm_module.client_override(client):
        result = await build_evidence(doc, CONCEPTS, [], run=RunContext(), settings=SETTINGS)

    # Order: extract, then support, then one embed; no embed for the dropped event.
    assert client.kinds == ["chat", "chat", "embed"]
    assert "evidence" in client.prompt(0).lower() or Q_OPEN in client.prompt(0)
    support_prompt = client.prompt(1)
    assert Q_OPEN in support_prompt and Q_STAFF in support_prompt
    assert Q_MISSING not in support_prompt  # failed the code check, never sent
    assert doc.text.count("cafeteria") == 1 and "cafeteria" not in support_prompt  # no document
    # Every quote in the support request passed the code check.
    sent = [json.loads(line) for line in support_prompt.splitlines() if line.startswith("{")]
    assert sent and all(find_quote(doc.text, s["quote"]).found for s in sent)
    assert result.llm_calls == 3

    statuses = [c.status for c in result.checks]
    assert statuses == [ClaimStatus.VERIFIED, ClaimStatus.VERIFIED, ClaimStatus.QUOTE_NOT_FOUND]
    assert all(c.verified_by == "code+llm" for c in result.checks if c.verified)

    (event,) = result.events
    assert event.occurred_on == date(2026, 3, 5) and event.available_at == AVAILABLE
    assert event.subject is not None and event.subject.country is None  # DE is not quoted
    assert event.slots["city"] == "Rotterdam" and "ghost" not in event.slots
    assert "group_key" not in event.slots  # "harbourside-plant" is not in any verified quote
    assert event.slots["subject_key"] == "harbourside works"
    assert event.embedding == unit(3)
    assert event.description == (
        "facility opened - Harbourside Works. Harbourside Works opened a plant in Rotterdam. "
        "Harbourside Works employs 240 people."
    )
    assert "invented" not in event.description
    assert event.concept.is_new and event.concept.label == "new_plant"
    assert event.concept.parent_id == CONCEPTS[0].id and event.concept.status == "proposed"
    assert len(event.claim_fingerprints) == 2


async def test_an_extracted_group_hint_is_kept_only_when_quoted() -> None:
    replies = full_text_replies()
    replies[0]["events"][0]["group_hint"] = "Rotterdam"
    client = Recorder(replies)
    client.vectors = [unit(3)]
    with llm_module.client_override(client):
        result = await build_evidence(
            website_doc(), CONCEPTS, [], run=RunContext(), settings=SETTINGS
        )
    (event,) = result.events
    assert event.slots["group_key"] == "Rotterdam"


async def test_an_event_with_no_verified_claim_costs_no_embed_call() -> None:
    reply = [
        {"claims": [claim(Q_OPEN)], "events": [event()]},
        verdicts(False),
    ]
    client = Recorder(reply)
    with llm_module.client_override(client):
        result = await build_evidence(
            website_doc(), CONCEPTS, [], run=RunContext(), settings=SETTINGS
        )
    assert client.kinds == ["chat", "chat"] and result.events == []
    assert result.checks[0].status == ClaimStatus.UNSUPPORTED and result.llm_calls == 2


async def test_no_passing_quote_means_no_support_call() -> None:
    client = Recorder([{"claims": [claim(Q_MISSING)], "events": [event()]}])
    with llm_module.client_override(client):
        result = await build_evidence(
            website_doc(), CONCEPTS, [], run=RunContext(), settings=SETTINGS
        )
    assert client.kinds == ["chat"] and result.events == [] and result.llm_calls == 1


async def test_embedding_clusters_with_a_recent_event_and_matches_an_existing_concept() -> None:
    parent = CONCEPTS[0]
    child = concept("new_plant", parent=parent.id, embedding=unit(3))
    existing = ClusterCandidate(
        event_id=uuid4(),
        cluster_id=uuid4(),
        event_type="facility_opened",
        occurred_on=date(2026, 3, 1),
        subject_key="harbourside works",
        group_key=None,
        embedding=unit(3),
    )
    client = Recorder(full_text_replies())
    client.vectors = [unit(3)]
    with llm_module.client_override(client):
        result = await build_evidence(
            website_doc(), [*CONCEPTS, child], [existing], run=RunContext(), settings=SETTINGS
        )
    (event_,) = result.events
    assert event_.cluster_id == existing.cluster_id
    assert event_.concept.concept_id == child.id and not event_.concept.is_new


async def test_excluded_and_unseeded_event_types_are_dropped() -> None:
    reply = [
        {
            "claims": [claim(Q_OPEN)],
            "events": [event(event_type="reorder_due"), event(event_type="made_up_type")],
        },
        verdicts(True),
    ]
    client = Recorder(reply)
    with llm_module.client_override(client):
        result = await build_evidence(
            website_doc(), CONCEPTS, [], run=RunContext(), settings=SETTINGS
        )
    assert result.events == [] and "embed" not in client.kinds


# --- process_document ------------------------------------------------------------------------


async def test_private_documents_are_refused_before_any_work() -> None:
    doc = website_doc().model_copy(update={"workspace_id": uuid4()})
    with pytest.raises(ValueError, match="parked"):
        await process_document(None, doc, run=RunContext())


async def test_process_document_persists_only_through_the_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    saved: dict[str, Any] = {}

    async def load_concepts(session: Any, **kw: Any) -> list[EventConceptRow]:
        calls.append("load_concepts")
        return CONCEPTS

    async def events_for_clustering(session: Any, **kw: Any) -> list[ClusterCandidate]:
        calls.append(f"events_for_clustering:{kw['as_of']:%Y-%m-%d}")
        return []

    async def save_claims(session: Any, checks: list[ClaimCheck]) -> dict[str, UUID]:
        calls.append("save_claims")
        return {c.fingerprint: uuid4() for c in checks}

    async def ensure_concept(session: Any, assignment: Any) -> UUID:
        calls.append(f"ensure_concept:{assignment.label}")
        return uuid4()

    async def save_events(session: Any, events: list[Any]) -> dict[str, UUID]:
        calls.append("save_events")
        saved["events"] = events
        return {}

    for fn in (load_concepts, events_for_clustering, save_claims, ensure_concept, save_events):
        monkeypatch.setattr(store, fn.__name__, fn)

    client = Recorder(full_text_replies())
    client.vectors = [unit(3)]
    as_of = datetime(2026, 7, 1, tzinfo=UTC)
    with llm_module.client_override(client):
        result = await process_document(
            None, website_doc(), run=RunContext(), as_of=as_of, settings=SETTINGS
        )
    assert calls[0] == "load_concepts"
    assert "events_for_clustering:2026-07-01" in calls  # as_of wins over the document's
    assert calls[-3:] == ["save_claims", "ensure_concept:new_plant", "save_events"]
    (new_event,) = saved["events"]
    assert len(new_event.claim_ids) == 2 and new_event.concept_id is not None
    assert len(result.checks) == 3


async def test_process_document_defaults_as_of_to_the_document(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[Any] = []

    async def load_concepts(session: Any, **kw: Any) -> list[EventConceptRow]:
        return CONCEPTS

    async def events_for_clustering(session: Any, **kw: Any) -> list[ClusterCandidate]:
        seen.append(kw["as_of"])
        return []

    async def save_claims(session: Any, checks: list[ClaimCheck]) -> dict[str, UUID]:
        return {c.fingerprint: uuid4() for c in checks}

    async def save_events(session: Any, events: list[Any]) -> dict[str, UUID]:
        return {}

    monkeypatch.setattr(store, "load_concepts", load_concepts)
    monkeypatch.setattr(store, "events_for_clustering", events_for_clustering)
    monkeypatch.setattr(store, "save_claims", save_claims)
    monkeypatch.setattr(store, "save_events", save_events)
    with llm_module.client_override(Forbidden()):
        await process_document(None, ted_doc(), run=RunContext(), settings=SETTINGS)
    assert seen and set(seen) == {AVAILABLE}
