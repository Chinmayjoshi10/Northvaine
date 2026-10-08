"""Likely bidders for open tenders (D81): award winners for the tender's codes and country,
verified by code. A fake TED sensor serves real recorded award notices; no network, no model."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest

from northvaine.brain.budget import RunContext
from northvaine.core.settings import Settings
from northvaine.radar import bidders
from northvaine.radar.models import RadarStream, RankedEntry
from northvaine.radar.run import seeded_concepts
from northvaine.sensors.base import SensorError, SensorQuery, SensorResult
from northvaine.sensors.ted import parse_notice
from tests.radar.test_brief import UNKNOWN, candidate, claim, gate, ranked

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "sensors" / "ted"
AS_OF = datetime(2026, 10, 5, 9, 0, tzinfo=UTC)
SETTINGS = Settings(_env_file=None)


def award_records() -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in sorted(FIXTURES.glob("*.json")):
        for exchange in json.loads(path.read_text(encoding="utf-8")):
            for notice in exchange["body_json"]["notices"]:
                if notice.get("notice-type") == "can-standard":
                    records.append(notice)
    return records


class FakeTed:
    def __init__(self, fail: bool = False) -> None:
        self.queries: list[SensorQuery] = []
        self.fail = fail

    async def search(self, query: SensorQuery, **_: Any) -> SensorResult:
        self.queries.append(query)
        if self.fail:
            raise SensorError("TED unavailable")
        docs = [parse_notice(r, fetched_at=AS_OF, settings=SETTINGS) for r in award_records()]
        return SensorResult(documents=docs, enumerable=True)


def tender_entry(name: str, codes: str, country: str = "DE") -> RankedEntry:
    c = candidate(
        name,
        [claim("C1", f"{name} tender")],
        stream=RadarStream.TENDER,
        window_end=date(2026, 10, 30),
        country=country,
    )
    events = [e.model_copy(update={"slots": {"cpv_codes": codes}}) for e in c.events]
    return ranked([(c.model_copy(update={"events": events}), gate(), UNKNOWN)])[0]


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> FakeTed:
    ted = FakeTed()
    monkeypatch.setattr(bidders, "get_sensor", lambda name, client, settings: ted)
    return ted


def test_the_award_query_uses_the_tenders_own_codes_and_country() -> None:
    entry = tender_entry("Stadt A", "45233250, 45233260")
    query = bidders.bidder_query(entry, AS_OF, SETTINGS)
    assert query is not None
    assert query.codes == ["cpv:45233250", "cpv:45233260"]
    assert query.countries == ["DE"] and [k.value for k in query.kinds] == ["contract_awarded"]
    assert query.published_to == date(2026, 10, 5)
    assert (query.published_to - query.published_from).days == SETTINGS.radar_bidder_lookback_days


def test_non_tenders_and_tenders_without_codes_get_no_query() -> None:
    announcement = ranked([(candidate("Brand B", [claim("C1", "launch")]), gate(), UNKNOWN)])[0]
    assert bidders.bidder_query(announcement, AS_OF, SETTINGS) is None
    assert bidders.bidder_query(tender_entry("Stadt A", ""), AS_OF, SETTINGS) is None


async def test_winners_are_verified_counted_and_never_withheld_persons(fake: FakeTed) -> None:
    entries, notes = await bidders.likely_bidders(
        [tender_entry("Stadt A", "45233250")],
        as_of=AS_OF,
        http=None,
        concepts=seeded_concepts(),
        run=RunContext(),
        settings=SETTINGS,
    )
    found = entries[0].likely_bidders
    assert found and len(found) <= SETTINGS.radar_bidder_max and notes == []
    assert [b.wins for b in found] == sorted((b.wins for b in found), reverse=True)
    for b in found:
        assert b.quote.startswith("Winner [") and b.name in b.quote
        assert not b.name.startswith("[")  # withheld natural persons never listed (D76)
        assert b.source_url.startswith("https://")


async def test_one_search_per_distinct_codes_and_country(fake: FakeTed) -> None:
    same = [tender_entry(f"Stadt {i}", "45233250") for i in range(3)]
    other = tender_entry("Ville B", "45233250", country="FR")
    await bidders.likely_bidders(
        [*same, other],
        as_of=AS_OF,
        http=None,
        concepts=seeded_concepts(),
        run=RunContext(),
        settings=SETTINGS,
    )
    assert len(fake.queries) == 2


async def test_the_query_cap_and_a_failing_source_become_notes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ted = FakeTed(fail=True)
    monkeypatch.setattr(bidders, "get_sensor", lambda name, client, settings: ted)
    capped = SETTINGS.model_copy(update={"radar_bidder_max_queries": 1})
    entries, notes = await bidders.likely_bidders(
        [tender_entry("Stadt A", "45233250"), tender_entry("Stadt B", "45112700")],
        as_of=AS_OF,
        http=None,
        concepts=seeded_concepts(),
        run=RunContext(),
        settings=capped,
    )
    assert all(e.likely_bidders == [] for e in entries)
    assert any("likely bidders not found for Stadt A" in n for n in notes)
    assert any("query cap reached" in n for n in notes)
