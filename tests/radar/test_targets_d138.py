"""D138: the client's target accounts, read from their own sites and checked like any lead."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from northvaine.brain import llm
from northvaine.brain.budget import RunContext
from northvaine.brain.replay import LEGACY_SETTINGS
from northvaine.core.settings import Settings
from northvaine.radar import run as run_module
from northvaine.radar.discover import DiscoverResult, RecordedPageFetcher
from northvaine.radar.models import TargetAccount
from northvaine.radar.partners import target_candidates
from northvaine.radar.run import run_radar, seeded_concepts
from tests.radar.test_partners_d136 import CFG, PAGE_TEXT, _doc, _spec
from tests.radar.test_run import FakeLlm, Spy

ACME = TargetAccount(name="Acme Tile and Stone", country="US", website="https://acme-tile.com/")
OTHER = TargetAccount(name="Other Co", country="US", website="https://other.example/")


def test_an_account_whose_site_names_the_offer_is_a_lead_on_the_list() -> None:
    page = _doc("Home", "https://acme-tile.com/", PAGE_TEXT)
    made, evidence, already, notes = target_candidates([(page, ACME)], _spec(), [], settings=CFG)
    assert [c.name for c in made] == ["Acme Tile and Stone"]  # the account's own name
    c = made[0]
    assert c.from_list and c.country == "US"
    assert c.events[0].event_type == "company_profile" and c.events[0].occurred_on is None
    assert all(cl.source_quote in PAGE_TEXT for cl in c.claims)
    assert evidence[0][1].checks[0].draft.source_quote in PAGE_TEXT
    assert not already and not notes


def test_an_account_naming_nothing_sold_or_not_read_is_noted_never_made() -> None:
    page = _doc("Home", "https://other.example/", "We make software for banks.")
    made, _, _, notes = target_candidates([(page, OTHER)], _spec(), [], settings=CFG)
    assert made == [] and len(notes) == 1 and "Other Co" in notes[0]


def test_an_account_already_found_is_marked_not_duplicated() -> None:
    page = _doc("Home", "https://acme-tile.com/", PAGE_TEXT)
    first, _, _, _ = target_candidates([(page, ACME)], _spec(), [], settings=CFG)
    existing = [first[0].model_copy(update={"from_list": False})]
    made, _, already, notes = target_candidates([(page, ACME)], _spec(), existing, settings=CFG)
    assert made == [] and already == {existing[0].key} and not notes


def test_legacy_recordings_read_no_account_sites() -> None:
    assert LEGACY_SETTINGS["radar_target_accounts"] is False


async def test_the_run_reads_each_account_site_and_gates_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = _doc("Home", "https://acme-tile.com/", PAGE_TEXT)
    seen: dict[str, Any] = {}

    async def fake_discover(spec: Any, queries: Any, **kwargs: Any) -> DiscoverResult:
        seen["website"] = [q.text for q in queries.get("website", [])]
        return DiscoverResult(
            documents=[page],
            leads=0,
            upgraded=[],
            notes=[],
            steered_urls=[],
            found_by={str(page.id): ["website:1"]},
        )

    monkeypatch.setattr(run_module, "discover", fake_discover)
    fake = FakeLlm()
    spy = Spy(fake, monkeypatch)
    settings = Settings(
        _env_file=None,
        radar_intent_search=False,
        radar_partner_discovery=False,
        radar_fit_max_accounts=0,
        radar_investigate_top=0,
        radar_site_guess_max_companies=0,
        radar_gate_concurrency=1,
    )
    with llm.client_override(fake):
        result = await run_radar(
            _spec(target_accounts=[ACME.model_dump(), OTHER.model_dump()]),
            as_of=datetime(2026, 10, 24, tzinfo=UTC),
            http=None,
            fetcher=RecordedPageFetcher([]),
            concepts=seeded_concepts(),
            run=RunContext(),
            settings=settings,
        )
    assert seen["website"] == ["https://acme-tile.com/", "https://other.example/"]
    assert "your list: 2 account site(s) read" in result.notes
    assert any(n.startswith("your list: Other Co") for n in result.notes)
    assert spy.of("gate") == ["US:acme tile and stone"]
