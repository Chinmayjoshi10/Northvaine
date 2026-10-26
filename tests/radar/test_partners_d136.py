"""D136: a distributor's own website found abroad becomes a lead by code. No network."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any
from uuid import uuid4

import pytest

from northvaine.brain import llm
from northvaine.brain.budget import RunContext
from northvaine.brain.replay import LEGACY_SETTINGS
from northvaine.core.models import EvidenceDocument
from northvaine.core.settings import Settings
from northvaine.radar import run as run_module
from northvaine.radar.discover import DiscoverResult, RecordedPageFetcher
from northvaine.radar.intent import intent_queries, partner_queries
from northvaine.radar.models import ClientSpec, RadarStream
from northvaine.radar.partners import partner_candidates
from northvaine.radar.run import run_radar, seeded_concepts
from tests.radar.test_run import FakeLlm, Spy

TODAY = date(2026, 10, 24)
CFG = Settings(_env_file=None)
PAGE_TEXT = (
    "Acme Tile & Stone is a family business. "
    "We import and distribute natural stone through 12 showrooms across Texas. "
    "Visit us today."
)


def _spec(**extra: object) -> ClientSpec:
    base: dict[str, Any] = {
        "id": "demo",
        "offer": "Natural stone",
        "markets": ["GB", "US"],
        "offer_terms": ["natural stone"],
        "buyer_roles": ["stone distributor", "building contractor"],
        "need_triggers": ["new hotel"],
        "catalogue_lines": [],
        "sensors": {
            "hmrc": [{"kinds": ["imports_recorded"], "codes": ["hs:6802"], "countries": ["GB"]}]
        },
        "channel": "both",
    }
    base.update(extra)
    return ClientSpec.model_validate(base)


def _doc(title: str, url: str, text: str) -> EvidenceDocument:
    return EvidenceDocument(
        id=uuid4(),
        source_name="tavily",
        url=url,
        title=title,
        text=text,
        available_at=datetime(2026, 10, 1, tzinfo=UTC),
    )


def test_one_partner_search_per_market_without_import_records() -> None:
    queries = partner_queries(_spec(), TODAY)
    assert len(queries) == 1  # GB has import records; only US is searched
    q = queries[0]
    assert q.countries == ["US"]
    assert q.text == "stone distributor natural stone showrooms United States"
    assert q.published_from is None and q.published_to is None and q.max_results == 5
    assert "building contractor" not in (q.text or "")  # channel roles only


def test_no_partner_search_for_a_direct_seller_or_without_channel_roles() -> None:
    assert partner_queries(_spec(channel="direct"), TODAY) == []
    assert partner_queries(_spec(buyer_roles=["building contractor"]), TODAY) == []
    assert partner_queries(_spec(sensors={}), TODAY)[0].countries == ["GB"]  # no records at all


def test_a_company_page_becomes_a_candidate_with_an_undated_profile_event() -> None:
    page = _doc("Acme Tile & Stone | Showrooms", "https://www.acme-tile.com/", PAGE_TEXT)
    made, evidence = partner_candidates([(page, "US")], _spec(), [], settings=CFG)
    assert len(made) == 1
    c = made[0]
    assert c.name == "Acme Tile & Stone" and c.country == "US" and c.roles == ["distributor"]
    assert c.stream == RadarStream.ANNOUNCEMENT
    assert [(e.event_type, e.occurred_on) for e in c.events] == [("company_profile", None)]
    assert c.events[0].claim_refs == [cl.ref for cl in c.claims] and c.claims
    for claim in c.claims:
        assert claim.source_quote in page.text and claim.verified_by == "code"
        assert claim.url == page.url and "natural stone" in claim.statement
    ((doc, ledger),) = evidence
    assert doc is page and all(ch.verified for ch in ledger.checks)
    assert len(ledger.checks) == len(c.claims)


def test_pages_that_are_not_a_company_site_or_name_no_offer_term_make_nothing() -> None:
    news = _doc("Hotel opens | Gulf News", "https://gulfnews.com/a", "Gulf News: natural stone.")
    other = _doc(
        "Tiles | Schefer GmbH",
        "https://www.steineundfliesen.at/en",
        "Schefer GmbH sells natural stone.",
    )
    no_term = _doc(
        "Acme Tile & Stone | Showrooms",
        "https://acme-tile.com/",
        "Acme Tile & Stone sells carpets.",
    )
    made, evidence = partner_candidates(
        [(news, "US"), (other, "US"), (no_term, "US")], _spec(), [], settings=CFG
    )
    assert made == [] and evidence == []


def test_an_existing_candidate_with_the_same_key_is_not_duplicated() -> None:
    page = _doc("Acme Tile & Stone | Showrooms", "https://acme-tile.com/", PAGE_TEXT)
    first, _ = partner_candidates([(page, "US")], _spec(), [], settings=CFG)
    again, evidence = partner_candidates([(page, "US")], _spec(), first, settings=CFG)
    assert again == [] and evidence == []
    twice, _ = partner_candidates([(page, "US"), (page, "US")], _spec(), [], settings=CFG)
    assert len(twice) == 1


def test_intent_searches_are_unchanged_and_legacy_settings_turn_discovery_off() -> None:
    assert len(intent_queries(_spec(), TODAY, 90)) == 4
    assert LEGACY_SETTINGS["radar_partner_discovery"] is False
    assert CFG.radar_partner_discovery and CFG.tavily_max_calls_per_run == 30


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch, clean_settings: None) -> None:
    monkeypatch.setenv("MODEL_FAST", "nvidia/Nemotron-3_5-Lightning")
    monkeypatch.setenv("MODEL_MID", "nvidia/nemotron-3-super-120b-a12b")
    monkeypatch.setenv("DAILY_BUDGET_USD", "10")
    monkeypatch.setenv("TOTAL_BUDGET_USD", "29")
    llm.get_settings.cache_clear()


async def test_the_run_adds_partner_searches_and_their_candidates_reach_the_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = _doc("Acme Tile & Stone | Showrooms", "https://acme-tile.com/", PAGE_TEXT)

    async def fake_discover(spec: Any, queries: Any, **kwargs: Any) -> DiscoverResult:
        index = next(
            i for i, q in enumerate(queries["tavily"], start=1) if "showrooms" in (q.text or "")
        )
        return DiscoverResult(
            documents=[page],
            leads=0,
            upgraded=[],
            notes=[],
            steered_urls=[],
            found_by={str(page.id): [f"tavily:{index}"]},
        )

    monkeypatch.setattr(run_module, "discover", fake_discover)
    fake = FakeLlm()
    spy = Spy(fake, monkeypatch)
    settings = Settings(
        _env_file=None,
        radar_intent_search=False,
        radar_fit_max_accounts=0,
        radar_investigate_top=0,
        radar_site_guess_max_companies=0,
        radar_gate_concurrency=1,
    )
    evidence: list[Any] = []
    with llm.client_override(fake):
        result = await run_radar(
            _spec(),
            as_of=datetime(2026, 10, 24, tzinfo=UTC),
            http=None,
            fetcher=RecordedPageFetcher([]),
            concepts=seeded_concepts(),
            run=RunContext(),
            settings=settings,
            evidence_out=evidence,
        )
    assert "partner discovery: 1 search(es)" in result.notes
    assert spy.of("gate") == ["US:acme tile stone"]
    assert any(r.checks and r.checks[0].draft.source_quote in PAGE_TEXT for _, r in evidence)
