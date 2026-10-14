"""UK HMRC trade data sensor (D102): request mapping, ranking, privacy, availability, evidence.
No network: every HTTP exchange is a recorded fixture or a hand-built response."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest

from northvaine.core.models import EventType
from northvaine.core.settings import Settings
from northvaine.radar.ledger import evidence_document_from_sensor
from northvaine.radar.structured import structured_evidence
from northvaine.sensors import hmrc
from northvaine.sensors.base import Sensor, SensorQuery, SensorRateLimited
from northvaine.sensors.hmrc import HmrcSensor
from northvaine.sensors.replay import load_exchanges, replay_transport

FIXTURE = (
    Path(__file__).parent.parent / "fixtures" / "sensors" / "hmrc" / "refrigerated_cases_1.json"
)
SETTINGS = Settings(_env_file=None)
IMPORTS = [EventType.IMPORTS_RECORDED]


async def no_sleep(seconds: float) -> None:
    return None


def query(**kw: Any) -> SensorQuery:
    base: dict[str, Any] = dict(
        kinds=IMPORTS,
        codes=["hs:841850"],
        countries=["GB"],
        published_from=date(2026, 5, 1),
        max_results=50,
    )
    base.update(kw)
    return SensorQuery(**base)


async def replay(q: SensorQuery, *, as_of: datetime | None = None):
    transport = replay_transport(load_exchanges(FIXTURE))
    async with httpx.AsyncClient(transport=transport) as client:
        sensor = HmrcSensor(client=client, settings=SETTINGS, sleep=no_sleep)
        return await sensor.search(q, as_of=as_of)


def test_is_a_sensor() -> None:
    assert isinstance(HmrcSensor(settings=SETTINGS), Sensor)
    assert HmrcSensor.enumerable is True


def test_codes_and_params() -> None:
    q = query(codes=["hs:841850", "cn:84185011", "cpv:39711130", "hs:841850"])
    assert hmrc.requested_codes(q) == ["841850", "84185011"]
    params = hmrc.build_params("841850", 202605, 202607, previous=False)
    assert params == {
        "$filter": "Hs6Code eq '841850'",
        "$expand": "Imports($filter=MonthId ge 202605 and MonthId le 202607;$expand=Trader)",
    }
    prev = hmrc.build_params("84185011", 202501, 202512, previous=True)
    assert prev["$filter"] == "Cn8Code eq '84185011'"
    assert prev["$expand"].endswith(";$select=TraderId,MonthId)")


def test_availability_is_after_the_month_and_lag() -> None:
    # July data was public by mid October (field test, 14 Oct)
    assert hmrc.month_published_on(202607, SETTINGS) == date(2026, 10, 9)
    assert hmrc.month_available_at(202607, SETTINGS) == datetime(2026, 10, 10, tzinfo=UTC)
    first, last = hmrc.window(query(), as_of=datetime(2026, 10, 5, tzinfo=UTC), settings=SETTINGS)
    assert (first, last) == (202605, 202606)


async def test_replay_lists_company_importers_ranked() -> None:
    result = await replay(query())
    docs = result.documents
    assert len(docs) == 9
    assert any("non-UK sellers" in n for n in result.notes)
    assert all(d.source == "hmrc" and d.meta["schema_ver"] == 1 for d in docs)
    assert all("AB10 1ZP" not in d.text for d in docs)
    new = [d for d in docs if d.meta["new_this_year"]]
    assert docs[: len(new)] == new  # new importers first
    for group in (new, docs[len(new) :]):
        keys = [(-len(d.meta["families"]), -d.meta["months_active"]) for d in group]
        assert keys == sorted(keys)
    assert sum(d.meta["new_this_year"] for d in docs) == 4
    for d in docs:
        assert d.text.splitlines()[0] == f"Importer: {d.meta['importer']}"
        assert d.url == f"https://api.uktradeinfo.com/Trader({d.meta['trader_id']})"
        assert d.available_at == hmrc.month_available_at(
            int(d.meta["last_month"].replace("-", "")), SETTINGS
        )
        new = d.meta["new_this_year"]
        assert ("none recorded in 2025" in d.text) is new
        if new:
            assert (
                f"New importer: first recorded importing these codes in {d.meta['first_month']}"
                in d.text
            )


async def test_as_of_bounds_the_request_and_drops_late_months() -> None:
    urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        urls.append(str(request.url))
        if len(urls) == 1:  # a late month the API should not have sent is dropped in code too
            return httpx.Response(
                200,
                json=body([imp(2, "EXAMPLE TRADING LTD"), imp(2, "EXAMPLE TRADING LTD", 202607)]),
            )
        return httpx.Response(200, json=body([]))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        sensor = HmrcSensor(client=client, settings=SETTINGS, sleep=no_sleep)
        result = await sensor.search(
            query(codes=["cn:12345678"]), as_of=datetime(2026, 10, 5, tzinfo=UTC)
        )
    assert "MonthId+le+202606" in urls[0]
    (doc,) = result.documents
    assert doc.meta["months"] == ["2026-06"]
    assert "dropped 1 import line(s) published after as_of" in result.notes


async def test_cap_keeps_the_best() -> None:
    full = await replay(query())
    top = await replay(query(max_results=3))
    assert top.truncated is True
    new = [d.external_id for d in full.documents if d.meta["new_this_year"]]
    old = [d.external_id for d in full.documents if not d.meta["new_this_year"]]
    # half the slots (rounded) for new importers, the best of each group
    assert [d.external_id for d in top.documents] == new[:2] + old[:1]


def test_split_legal_form_still_counts_as_a_company() -> None:
    assert hmrc._is_company("EXAMPLE TRADING LIMITE D", SETTINGS)
    assert hmrc._is_company("EXAMPLE PLC", SETTINGS)
    assert not hmrc._is_company("JOHN EXAMPLE", SETTINGS)
    assert not hmrc._is_company("JOHN EXAMPLE AS AGENT", SETTINGS)  # "as" is a word, not a form


@pytest.mark.parametrize(
    "q, note",
    [
        (dict(countries=["FR"]), "UK imports only"),
        (dict(codes=["cpv:39711130"]), "no hs: or cn: code"),
        (dict(kinds=[EventType.TENDER_PUBLISHED]), "no imports_recorded kind"),
    ],
)
async def test_nothing_fetched_when_the_query_does_not_apply(q: dict[str, Any], note: str) -> None:
    def fail(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no request expected")

    async with httpx.AsyncClient(transport=httpx.MockTransport(fail)) as client:
        result = await HmrcSensor(client=client, settings=SETTINGS).search(query(**q))
    assert result.documents == [] and note in result.notes[0]


def body(imports: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "value": [{"Cn8Code": "12345678", "Cn8LongDescription": "Test goods", "Imports": imports}]
    }


def imp(tid: int, name: str, month: int = 202606, postcode: str = "ZZ1 1ZZ") -> dict[str, Any]:
    return {
        "TraderId": tid,
        "MonthId": month,
        "Trader": {"TraderId": tid, "CompanyName": name, "PostCode": postcode, "Address1": "x"},
    }


async def test_names_without_a_legal_form_are_never_kept() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if len(calls) == 1:
            return httpx.Response(
                200,
                json=body(
                    [
                        imp(1, "JOHN EXAMPLE"),
                        imp(1, "JOHN EXAMPLE", 202607),
                        imp(2, "EXAMPLE TRADING LTD"),
                        imp(3, "EXAMPLE OVERSEAS LIMITED", postcode="AB10 1ZP"),
                    ]
                ),
            )
        return httpx.Response(200, json=body([{"TraderId": 2, "MonthId": 202503}]))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        sensor = HmrcSensor(client=client, settings=SETTINGS, sleep=no_sleep)
        result = await sensor.search(query(codes=["cn:12345678"]))
    assert [d.meta["importer"] for d in result.documents] == ["EXAMPLE TRADING LTD"]
    assert result.documents[0].meta["new_this_year"] is False
    assert "Address1" not in json.dumps(result.documents[0].meta)
    assert "x" not in result.documents[0].text.split("\n")[1:2]
    assert "dropped 1 trader(s) with no company legal form" in result.notes
    assert "JOHN" not in json.dumps([d.model_dump(mode="json") for d in result.documents])


async def test_rate_limit_is_raised() -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(429, headers={"retry-after": "30"}))
    ) as client:
        with pytest.raises(SensorRateLimited) as info:
            await HmrcSensor(client=client, settings=SETTINGS, sleep=no_sleep).search(query())
    assert info.value.retry_after == 30


async def test_structured_evidence_quotes_every_line_and_names_the_importer() -> None:
    doc = (await replay(query())).documents[0]
    drafts = structured_evidence(evidence_document_from_sensor(doc))
    assert drafts is not None
    claims, events = drafts
    assert all(c.source_quote in doc.text for c in claims)
    assert len(claims) == len(doc.text.splitlines())
    assert claims[0].subject is not None and claims[0].subject.role == "importer"
    assert claims[0].subject.country == "GB"
    assert "Country: GB" in [c.source_quote for c in claims]  # grounds the subject's country
    (event,) = events
    assert event.event_type == "imports_recorded"
    assert event.claim_indices == list(range(len(claims)))
    assert event.slots["last_month"] == doc.meta["last_month"]
    assert event.slots["new_this_year"] is doc.meta["new_this_year"]
    assert event.occurred_on == date(
        int(doc.meta["last_month"][:4]), int(doc.meta["last_month"][5:]), 1
    )
