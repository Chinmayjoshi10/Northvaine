"""Company fit from the company's own website (D96): code-only checks, fake search and pages."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from northvaine.core.settings import Settings
from northvaine.radar import fit as fit_module
from northvaine.radar.fit import company_fit, domain_matches, fit_sentences, registrable
from northvaine.radar.models import (
    Candidate,
    ClientSpec,
    GateDecision,
    RadarStream,
    RankedEntry,
    SkepticFinding,
    UpgradedPage,
)
from northvaine.sensors.base import SensorDocument, SensorResult, SourceTier, content_hash

SETTINGS = Settings(_env_file=None)
NOW = datetime(2026, 10, 9, tzinfo=UTC)


def test_registrable_domains() -> None:
    assert registrable("https://www.acme-works.co.uk/products") == "acme-works.co.uk"
    assert registrable("https://shop.acme.de/x") == "acme.de"


def test_a_site_counts_only_when_its_domain_carries_the_name() -> None:
    assert domain_matches("Raffalli TP", "https://www.raffalli-tp.fr/", SETTINGS)
    assert domain_matches("Société Raffalli SAS", "https://raffalli.com", SETTINGS)
    assert not domain_matches("Raffalli TP", "https://www.pagesjaunes.fr/raffalli", SETTINGS)
    assert not domain_matches("SAS TP", "https://www.sas.com", SETTINGS)  # legal forms only


def test_fit_sentences_prefer_stated_terms_and_cap() -> None:
    text = (
        "We lay granite paving for town centres. We also supply concrete kerbs to builders. "
        "Our team is based in Ajaccio and works across Corsica."
    )
    found = fit_sentences(text, {"granite"}, {"kerb"}, limit=5)
    assert [(t, lvl) for _, t, lvl in found] == [("granite", "stated"), ("kerb", "related")]
    assert all(s in text for s, _, _ in found)
    assert len(fit_sentences(text, {"granite"}, {"kerb"}, limit=1)) == 1


class FakeSensor:
    def __init__(self, results: list[list[str]]) -> None:
        self.results = results
        self.queries: list[Any] = []

    async def search(self, query: Any) -> SensorResult:
        self.queries.append(query)
        urls = self.results.pop(0)
        docs = [
            SensorDocument(
                source="tavily",
                tier=SourceTier.REPORTED,
                url=u,
                text="snippet",
                content_hash=content_hash(u),
                fetched_at=NOW,
                available_at=NOW,
            )
            for u in urls
        ]
        return SensorResult(documents=docs, notes=[], enumerable=False)


class FakeFetcher:
    def __init__(self, pages: dict[str, str]) -> None:
        self.pages = pages

    async def fetch(self, url: str) -> UpgradedPage:
        return UpgradedPage(
            lead_url=url,
            final_url=url,
            status=200,
            fetched_at=NOW,
            title="t",
            text=self.pages.get(url),
            refused=None if url in self.pages else "http_404",
        )


def entry(role: str, stream: RadarStream = RadarStream.AWARD) -> RankedEntry:
    c = Candidate(
        key="FR:raffalli tp",
        name="Raffalli TP",
        country="FR",
        aliases=[],
        roles=["winner"],
        stream=stream,
        streams=[stream],
        events=[],
        claims=[],
        window_start=date(2026, 10, 6),
        window_end=None,
        window_estimated=False,
        window_note="",
    )
    gate = GateDecision(
        passed=True,
        rejected_as=None,
        by="llm",
        reason="r",
        direct_buyer=True,
        buyer_reason="b",
        demand_reason="d",
        suggested_action="s",
        cited_refs=[],
    )
    return RankedEntry(
        rank=1,
        candidate=c,
        gate=gate,
        skeptic=SkepticFinding(stance="unknown", against=[], open_questions=[]),
        strength="medium",
        rank_reasons=[],
        requirement="stated",
        account_role=role,
        evidence_level="project_requirement",
    )


SPEC = ClientSpec(
    id="c", offer="paving", markets=["FR"], sensors={}, offer_terms=["granite"],
    related_terms=["kerb"],
)  # fmt: skip


async def test_company_fit_quotes_the_companys_own_page(monkeypatch: Any) -> None:
    sensor = FakeSensor(
        [
            ["https://annuaire.example/raffalli", "https://www.raffalli-tp.fr/"],
            ["https://www.raffalli-tp.fr/realisations", "https://other.fr/x"],
        ]
    )
    monkeypatch.setattr(fit_module, "get_sensor", lambda *a, **k: sensor)
    page = "Raffalli TP pose du granite pour les places publiques. Contactez-nous."
    evidence: list[Any] = []
    out, notes = await company_fit(
        [entry("awarded_contractor")],
        SPEC,
        http=None,
        fetcher=FakeFetcher({"https://www.raffalli-tp.fr/realisations": page}),
        as_of=NOW,
        settings=SETTINGS,
        evidence_out=evidence,
    )
    e = out[0]
    assert e.company_site == "raffalli-tp.fr"
    assert e.fit_level == "stated"
    assert e.company_fit[0].quote in page
    assert sensor.queries[1].domains == ["raffalli-tp.fr"]
    # the quote is stored as a verified claim on the stored page text
    doc, ledger = evidence[0]
    check = ledger.checks[0]
    assert check.verified and doc.text[check.quote_offset :].startswith(check.draft.source_quote)
    assert not notes


async def test_no_matching_domain_means_no_fit(monkeypatch: Any) -> None:
    sensor = FakeSensor([["https://annuaire.example/raffalli"]])
    monkeypatch.setattr(fit_module, "get_sensor", lambda *a, **k: sensor)
    out, notes = await company_fit(
        [entry("awarded_contractor")], SPEC, http=None, fetcher=FakeFetcher({}), as_of=NOW,
        settings=SETTINGS,
    )  # fmt: skip
    assert out[0].company_fit == [] and out[0].company_site is None
    assert "no official site found" in notes[0]


async def test_tenders_and_suppliers_are_not_checked(monkeypatch: Any) -> None:
    sensor = FakeSensor([])
    monkeypatch.setattr(fit_module, "get_sensor", lambda *a, **k: sensor)
    entries = [entry("demand_source", RadarStream.TENDER), entry("supplier")]
    out, _ = await company_fit(
        entries, SPEC, http=None, fetcher=FakeFetcher({}), as_of=NOW, settings=SETTINGS
    )
    assert out == entries and sensor.queries == []


def test_menus_are_not_fit_quotes() -> None:
    menu = "Nos Engagements Accessibilité Granite Durabilité Le Changement Contact Plan"
    assert fit_sentences(menu, {"granite"}, set(), limit=5) == []
    prose = "Nous posons du granite pour les places et les rues du centre ancien."
    assert fit_sentences(prose, {"granite"}, set(), limit=5)
