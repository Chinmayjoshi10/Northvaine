"""D117: investigate the top leads within the search cap. Fake search, pages and ledger."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from northvaine.brain.budget import RunContext
from northvaine.brain.replay import LEGACY_SETTINGS
from northvaine.core.models import (
    ClaimCheck,
    ClaimDraft,
    ClaimStatus,
    ConceptAssignment,
    Eligibility,
    EvidenceKind,
    LedgerResult,
    PendingEvent,
    SubjectMention,
)
from northvaine.core.settings import Settings
from northvaine.radar import investigate as inv
from northvaine.radar.investigate import investigate, rerank
from northvaine.radar.models import (
    CandidateClaim,
    CandidateEvent,
    ClientSpec,
    RadarStream,
    RankedEntry,
    RegisterFacts,
)
from northvaine.radar.verify import claim_fingerprint
from northvaine.sensors.base import SensorDocument, SensorResult, SourceTier, content_hash
from tests.radar.test_fit import FakeFetcher, entry

NOW = datetime(2026, 10, 20, tzinfo=UTC)
CFG = Settings(_env_file=None)
SPEC = ClientSpec(id="c", offer="paving", markets=["GB"], sensors={}, offer_terms=["granite"])


class FakeSensor:
    """Returns the next list of (url, text) per search."""

    def __init__(self, results: list[list[tuple[str, str]]]) -> None:
        self.results = list(results)
        self.queries: list[Any] = []

    async def search(self, query: Any) -> SensorResult:
        self.queries.append(query)
        found = self.results.pop(0) if self.results else []
        docs = [
            SensorDocument(
                source="tavily",
                tier=SourceTier.REPORTED,
                url=u,
                title="t",
                text=text,
                content_hash=content_hash(u),
                fetched_at=NOW,
                available_at=NOW,
            )
            for u, text in found
        ]
        return SensorResult(documents=docs, notes=[], enumerable=False)


def lead(name: str, rank_: int, *, events: list[Any] | None = None) -> RankedEntry:
    e = entry("importer_of_record", RadarStream.TRADE)
    claim = CandidateClaim(
        ref="C1",
        fingerprint=f"fp-{name}",
        document_id=uuid5(NAMESPACE_URL, name),
        statement=f"{name} imports.",
        source_quote="Commodity 680221: imported",
        source_name="hmrc",
        url="https://example.org/r",
        available_at=NOW,
        evidence_kind=EvidenceKind.STRUCTURED,
        verified_by="code",
        upgraded_from=None,
    )
    c = e.candidate.model_copy(
        update={
            "key": f"GB:{name.casefold()}",
            "name": name,
            "country": "GB",
            "claims": [claim],
            "events": events or [],
            "company_register": RegisterFacts(number="1", name=name, status="active"),
        }
    )
    return e.model_copy(update={"candidate": c, "rank": rank_, "evidence_level": "proven_buyer"})


def page(url: str, text: str) -> tuple[str, str]:
    return url, text


def fake_ledger(
    monkeypatch: Any, facts: dict[str, list[tuple[str, str, date | None]]]
) -> list[str]:
    """build_evidence stand-in: one verified claim and event per (subject, quote, date) of the
    document's url. The quote is checked against the text, as the real ledger does."""
    seen: list[str] = []

    async def build(doc: Any, concepts: Any, recent: Any, **kw: Any) -> LedgerResult:
        seen.append(doc.url)
        checks, events = [], []
        for subject, quote, when in facts.get(doc.url, []):
            assert quote in doc.text, "the fake ledger needs the quote in the stored text"
            statement = f"{subject}: {quote}"
            fp = claim_fingerprint(doc.id, statement, quote)
            checks.append(
                ClaimCheck(
                    document_id=doc.id,
                    draft=ClaimDraft(
                        statement=statement,
                        source_quote=quote,
                        subject=SubjectMention(name=subject, role="company"),
                        extracted_by="llm",
                    ),
                    status=ClaimStatus.VERIFIED,
                    quote_offset=doc.text.index(quote),
                    verified_by="code",
                    fingerprint=fp,
                )
            )
            events.append(
                PendingEvent(
                    event_type="expansion",
                    claim_fingerprints=[fp],
                    occurred_on=when,
                    available_at=doc.available_at,
                    subject=SubjectMention(name=subject, country="GB", role="company"),
                    description=statement,
                    concept=ConceptAssignment(
                        level=0, label="expansion", description="d", status="active", is_new=False
                    ),
                    cluster_id=uuid5(NAMESPACE_URL, fp),
                    fingerprint=f"ev-{fp}",
                )
            )
        return LedgerResult(
            document_id=doc.id,
            eligibility=Eligibility(kind=EvidenceKind.FULL_TEXT),
            checks=checks,
            events=events,
        )

    monkeypatch.setattr(inv, "build_evidence", build)
    return seen


def run_ctx() -> RunContext:
    return RunContext()


async def go(
    entries: list[RankedEntry],
    sensor: FakeSensor,
    monkeypatch: Any,
    pages: dict[str, str],
    settings: Settings = CFG,
    evidence_out: list[Any] | None = None,
) -> tuple[list[RankedEntry], list[str]]:
    monkeypatch.setattr(inv, "get_sensor", lambda *a, **k: sensor)
    return await investigate(
        entries,
        SPEC,
        http=None,
        fetcher=FakeFetcher(pages),
        concepts=[],
        run=run_ctx(),
        as_of=NOW,
        settings=settings,
        evidence_out=evidence_out,
    )


async def test_at_most_two_searches_per_lead_and_the_run_cap(monkeypatch: Any) -> None:
    sensor = FakeSensor([])  # nothing ever names the company
    fake_ledger(monkeypatch, {})
    entries = [lead(f"Alpha{i} Ltd", i + 1) for i in range(5)]
    out, notes = await go(entries, sensor, monkeypatch, {})
    assert len(sensor.queries) == 6  # 3 leads (radar_investigate_top) x 2 searches
    assert out == entries
    assert notes[-1] == "investigated 3 lead(s): 6 search(es), 0 new fact(s)"
    tight = Settings(_env_file=None, radar_investigate_top=5, radar_investigate_max_searches=3)
    sensor = FakeSensor([])
    await go(entries, sensor, monkeypatch, {}, tight)
    assert len(sensor.queries) == 3  # the run cap, though 5 leads and 2 each would be 10


async def test_rephrase_only_when_no_result_names_the_company(monkeypatch: Any) -> None:
    fake_ledger(monkeypatch, {})
    named = FakeSensor([[("https://news.example/a", "Alpha Ltd opens a new unit.")]])
    await go([lead("Alpha Ltd", 1)], named, monkeypatch, {})
    assert len(named.queries) == 1
    q = named.queries[0]
    assert q.text == '"Alpha Ltd" news expansion project'
    assert q.countries == ["GB"]
    assert q.published_to == NOW.date()
    assert q.published_from == NOW.date() - timedelta(days=365)

    silent = FakeSensor([[("https://news.example/b", "Nothing about it.")]])
    await go([lead("Alpha Ltd", 1)], silent, monkeypatch, {})
    assert [q.text for q in silent.queries] == ['"Alpha Ltd" news expansion project', '"Alpha Ltd"']


async def test_the_registered_name_is_searched_when_known(monkeypatch: Any) -> None:
    e = lead("Alpha Ltd", 1)
    reg = e.candidate.company_register.model_copy(update={"name": "ALPHA STONE LIMITED"})
    e = e.model_copy(update={"candidate": e.candidate.model_copy(update={"company_register": reg})})
    sensor = FakeSensor([[("https://news.example/a", "Alpha Stone opens a unit.")]])
    fake_ledger(monkeypatch, {})
    await go([e], sensor, monkeypatch, {})
    assert sensor.queries[0].text.startswith('"ALPHA STONE LIMITED" ')


async def test_only_verified_facts_about_this_company_attach(monkeypatch: Any) -> None:
    url = "https://news.example/a"
    text = "Alpha Ltd opens a second plant in 2026. Beta Ltd signs a contract in 2026."
    q1, q2 = "Alpha Ltd opens a second plant in 2026.", "Beta Ltd signs a contract in 2026."
    sensor = FakeSensor([[(url, "Alpha Ltd in the news")]])
    fake_ledger(
        monkeypatch,
        {url: [("Alpha Ltd", q1, date(2026, 10, 1)), ("Beta Ltd", q2, date(2026, 10, 2))]},
    )
    saved: list[Any] = []
    out, notes = await go(
        [lead("Alpha Ltd", 1)], sensor, monkeypatch, {url: text}, evidence_out=saved
    )
    c = out[0].candidate
    assert [k.ref for k in c.claims] == ["C1", "C2"]  # renumbered after the existing C1
    assert c.claims[1].source_quote == q1
    assert all("Beta" not in k.statement for k in c.claims)
    assert [e.occurred_on for e in c.events] == [date(2026, 10, 1)]
    assert c.events[0].claim_refs == ["C2"]
    assert RadarStream.ANNOUNCEMENT in c.streams
    assert "Investigated: 1 new fact(s) from 1 source(s)" in out[0].rank_reasons
    assert notes[-1] == "investigated 1 lead(s): 1 search(es), 1 new fact(s)"
    assert len(saved) == 1  # the document and its ledger result are kept for saving the run


async def test_deny_listed_hosts_are_not_read(monkeypatch: Any) -> None:
    denied = CFG.fetch_deny_hosts[0]
    url = f"https://{denied}/alpha"
    sensor = FakeSensor([[(url, "Alpha Ltd page")]])
    seen = fake_ledger(monkeypatch, {url: [("Alpha Ltd", "Alpha Ltd page", None)]})
    out, _ = await go([lead("Alpha Ltd", 1)], sensor, monkeypatch, {url: "Alpha Ltd page"})
    assert seen == []
    assert out[0].candidate.claims == lead("Alpha Ltd", 1).candidate.claims


async def test_documents_per_lead_are_capped(monkeypatch: Any) -> None:
    urls = [f"https://news.example/{i}" for i in range(5)]
    sensor = FakeSensor([[(u, "Alpha Ltd news") for u in urls]])
    seen = fake_ledger(monkeypatch, {})
    await go([lead("Alpha Ltd", 1)], sensor, monkeypatch, {u: "Alpha Ltd news" for u in urls})
    assert len(seen) == CFG.radar_investigate_max_docs == 3


async def test_legacy_zero_makes_no_searches(monkeypatch: Any) -> None:
    assert LEGACY_SETTINGS["radar_investigate_top"] == 0
    sensor = FakeSensor([])
    off = Settings(_env_file=None, radar_investigate_top=0)
    entries = [lead("Alpha Ltd", 1)]
    out, notes = await go(entries, sensor, monkeypatch, {}, off)
    assert sensor.queries == [] and out == entries and notes == []


def test_a_new_dated_event_lifts_a_lead_after_reranking() -> None:
    plain = lead("Alpha Ltd", 1)
    plain = plain.model_copy(
        update={
            "candidate": plain.candidate.model_copy(update={"stream": RadarStream.ANNOUNCEMENT})
        }
    )
    other = lead("Beta Ltd", 2)
    other = other.model_copy(
        update={
            "candidate": other.candidate.model_copy(update={"stream": RadarStream.ANNOUNCEMENT})
        }
    )
    entries = rerank([plain, other], SPEC, as_of=NOW, settings=CFG)
    assert [e.candidate.name for e in entries] == ["Alpha Ltd", "Beta Ltd"]  # name breaks the tie
    dated = other.candidate.model_copy(
        update={
            "events": [
                inv_event(date(2026, 10, 10)),
            ]
        }
    )
    lifted = rerank(
        [entries[0], entries[1].model_copy(update={"candidate": dated})],
        SPEC,
        as_of=NOW,
        settings=CFG,
    )
    assert [e.candidate.name for e in lifted] == ["Beta Ltd", "Alpha Ltd"]
    assert [e.rank for e in lifted] == [1, 2]


def inv_event(when: date) -> Any:
    return CandidateEvent(
        event_type="expansion",
        description="d",
        occurred_on=when,
        available_at=NOW,
        claim_refs=["C1"],
        slots={},
        fingerprint="ev-x",
    )
