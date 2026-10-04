"""Replay leakage: no sensor may leak the future into an as_of replay (T3.6). No network."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from pydantic import SecretStr

from northvaine.core.documents import assert_available
from northvaine.core.settings import Settings
from northvaine.sensors.base import (
    LeakageError,
    ReplayUnsupported,
    SensorDocument,
    SensorQuery,
    content_hash,
)
from northvaine.sensors.registry import get_sensor
from northvaine.sensors.replay import load_exchanges, replay_transport
from northvaine.sensors.website import WebsiteSensor

ROOT = Path(__file__).parent.parent / "fixtures"
SETTINGS = Settings(_env_file=None, ted_min_interval_seconds=0, tavily_api_key=SecretStr("k"))


def spec_query(sensor: str) -> SensorQuery:
    spec = json.loads((ROOT / "clients" / "stone_supplier.json").read_text(encoding="utf-8"))
    return SensorQuery.model_validate(spec["sensors"][sensor][0])


def recorded_client(sensor: str, *, match_body: bool) -> httpx.AsyncClient:
    exchanges = []
    for path in sorted((ROOT / "sensors" / sensor).glob("stone_supplier_*.json")):
        exchanges.extend(load_exchanges(path))
    return httpx.AsyncClient(transport=replay_transport(exchanges, match_body=match_body))


async def test_ted_replay_returns_nothing_after_as_of() -> None:
    async with recorded_client("ted", match_body=True) as http:
        full = await get_sensor("ted", client=http, settings=SETTINGS).search(spec_query("ted"))
    times = sorted({d.available_at for d in full.documents if d.available_at})
    assert len(times) >= 2, "fixture needs notices available at two different times"
    as_of = times[0] + (times[-1] - times[0]) / 2
    assert times[0] <= as_of < times[-1]

    # The as_of request body differs from the recorded one, so serve the same recorded pages
    # regardless of body: the sensor itself must hold back what is not yet available.
    async with recorded_client("ted", match_body=False) as http:
        result = await get_sensor("ted", client=http, settings=SETTINGS).search(
            spec_query("ted"), as_of=as_of
        )
    assert result.documents
    assert len(result.documents) < len(full.documents)
    assert all(d.available_at is not None and d.available_at <= as_of for d in result.documents)
    assert_available(result.documents, as_of)


async def test_ted_as_of_before_everything_leaks_nothing() -> None:
    async with recorded_client("ted", match_body=False) as http:
        result = await get_sensor("ted", client=http, settings=SETTINGS).search(
            spec_query("ted"), as_of=datetime(2000, 1, 1, tzinfo=UTC)
        )
    assert result.documents == []


@pytest.mark.parametrize("name", ["tavily", "website"])
async def test_live_web_sensors_refuse_as_of(name: str) -> None:
    def no_network(request: httpx.Request) -> httpx.Response:
        raise AssertionError("a refused replay must not touch the network")

    http = httpx.AsyncClient(transport=httpx.MockTransport(no_network))
    sensor = get_sensor(name, client=http, settings=SETTINGS)
    with pytest.raises(ReplayUnsupported):
        await sensor.search(
            SensorQuery(text="https://acme.test/"), as_of=datetime(2026, 6, 1, tzinfo=UTC)
        )


def doc(available_at: datetime | None, fetched_at: datetime) -> SensorDocument:
    text = "text"
    return SensorDocument(
        source="tavily",
        tier="reported",
        url="https://x.test/a",
        text=text,
        content_hash=content_hash(text),
        fetched_at=fetched_at,
        available_at=available_at,
    )


def test_assert_available_raises_on_a_leaking_list() -> None:
    as_of = datetime(2026, 6, 1, tzinfo=UTC)
    fetched = as_of + timedelta(days=30)
    ok = doc(as_of - timedelta(days=1), fetched)
    leak = doc(as_of + timedelta(days=1), fetched)
    assert_available([ok], as_of)
    with pytest.raises(LeakageError):
        assert_available([ok, leak], as_of)
    with pytest.raises(LeakageError):
        assert_available([doc(None, fetched)], as_of)


async def test_results_report_enumerable_matching_the_sensor_class() -> None:
    assert get_sensor("ted").enumerable is True
    assert get_sensor("tavily").enumerable is False
    assert get_sensor("website").enumerable is False

    async with recorded_client("ted", match_body=True) as http:
        ted = await get_sensor("ted", client=http, settings=SETTINGS).search(spec_query("ted"))
    assert ted.documents
    assert ted.enumerable is True

    async with recorded_client("tavily", match_body=True) as http:
        tavily = await get_sensor("tavily", client=http, settings=SETTINGS).search(
            spec_query("tavily")
        )
    assert tavily.documents
    assert tavily.enumerable is False

    web = ROOT / "web"

    def page(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        body = (web / "home.html").read_text(encoding="utf-8")
        return httpx.Response(200, text=body, headers={"content-type": "text/html"})

    async def public(host: str) -> list[str]:
        return ["93.184.216.34"]

    async with httpx.AsyncClient(transport=httpx.MockTransport(page)) as http:
        sensor = WebsiteSensor(client=http, resolver=public, settings=SETTINGS)
        site = await sensor.search(SensorQuery(text="https://acme.test/", max_results=1))
    assert site.documents
    assert site.enumerable is False
