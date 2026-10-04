"""Tavily sensor: recorded results, request replay, errors, key hygiene (T3.5). No network."""

from __future__ import annotations

import json
import logging
from datetime import UTC, date, datetime
from pathlib import Path

import httpx
import pytest
from pydantic import SecretStr

from northvaine.core.settings import ConfigError, Settings
from northvaine.sensors import tavily
from northvaine.sensors.base import (
    DateFlag,
    ReplayUnsupported,
    SensorError,
    SensorQuery,
    SensorRateLimited,
)
from northvaine.sensors.replay import RecordedExchange, load_exchanges, replay_transport
from northvaine.sensors.tavily import TavilyBudgetStopError, TavilySensor, parse_result

ROOT = Path(__file__).parent.parent
FIXTURES = ROOT / "fixtures" / "sensors" / "tavily"
CLIENTS = ROOT / "fixtures" / "clients"
SENTINEL = "SENTINEL-not-a-real-key"
FETCHED = datetime(2026, 10, 4, 9, 0, tzinfo=UTC)


def make_settings(**kw: object) -> Settings:
    return Settings(_env_file=None, tavily_api_key=SecretStr(SENTINEL), **kw)


SETTINGS = make_settings()


def all_exchanges() -> list[RecordedExchange]:
    out: list[RecordedExchange] = []
    for path in sorted(FIXTURES.glob("*.json")):
        out.extend(load_exchanges(path))
    return out


def recorded_results() -> list[dict]:
    return [r for ex in all_exchanges() for r in ex.body_json["results"]]


def client_queries() -> list[SensorQuery]:
    out = []
    for path in sorted(CLIENTS.glob("*.json")):
        spec = json.loads(path.read_text(encoding="utf-8"))
        out.extend(SensorQuery.model_validate(q) for q in spec["sensors"].get("tavily", []))
    return out


def sensor(transport: httpx.MockTransport, settings: Settings = SETTINGS) -> TavilySensor:
    return TavilySensor(client=httpx.AsyncClient(transport=transport), settings=settings)


def query(**kw: object) -> SensorQuery:
    return SensorQuery(text="some announcement", **kw)


def fixed(status: int, **kw: object) -> httpx.MockTransport:
    return httpx.MockTransport(lambda request: httpx.Response(status, **kw))


def empty_ok() -> httpx.MockTransport:
    return httpx.MockTransport(lambda request: httpx.Response(200, json={"results": []}))


# ------------------------------------------------------------------ replay of the recordings


async def test_every_recorded_request_is_served_and_parsed() -> None:
    exchanges = all_exchanges()
    assert exchanges
    recorded_bodies = [json.dumps(e.request_json, sort_keys=True) for e in exchanges]
    transport = replay_transport(exchanges, match_body=True)
    matched = 0
    for q in client_queries():
        body, _ = tavily.build_search_request(q, settings=SETTINGS)
        if json.dumps(body, sort_keys=True) not in recorded_bodies:
            continue  # the recorder refused that response (PII); no fixture exists
        result = await sensor(transport).search(q)
        matched += 1
        assert result.enumerable is False
        assert result.documents
    assert matched == len(exchanges)


async def test_authorization_header_and_url() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"results": []})

    await sensor(httpx.MockTransport(handler)).search(query())
    assert str(seen[0].url) == f"{SETTINGS.tavily_api_url}/search"
    assert seen[0].headers["authorization"] == f"Bearer {SENTINEL}"
    assert SENTINEL not in seen[0].content.decode()


async def test_builder_notes_reach_the_result() -> None:
    result = await sensor(empty_ok()).search(query(countries=["DE", "FR"]))
    assert any("country omitted" in n for n in result.notes)


async def test_documents_from_recorded_fixtures() -> None:
    docs = []
    for ex in all_exchanges():
        q = SensorQuery(text=ex.request_json["query"])
        docs.extend((await sensor(replay_transport([ex], match_body=False)).search(q)).documents)
    assert docs
    for doc in docs:
        assert doc.source == "tavily"
        assert doc.available_at == doc.fetched_at
        assert DateFlag.CLAIMED_DATE_UNTRUSTED in doc.date_flags
        assert doc.meta["text_kind"] in ("raw", "snippet")
        assert "request_id" not in doc.meta
        assert "score" in doc.meta and "published_date" in doc.meta
        assert doc.content_hash
    assert any(d.published_on is not None for d in docs)
    assert {d.meta["text_kind"] for d in docs} == {"raw", "snippet"}


def test_parse_each_recorded_result() -> None:
    for item in recorded_results():
        try:
            doc = parse_result(item, fetched_at=FETCHED)
        except ValueError:
            assert not item.get("raw_content") and not item.get("content")
            continue
        raw = item.get("raw_content")
        if raw:
            assert doc.text == raw and doc.meta["text_kind"] == "raw"
        else:
            assert doc.text == item["content"] and doc.meta["text_kind"] == "snippet"
        assert doc.available_at == doc.fetched_at == FETCHED
        assert doc.meta["published_date"] == item.get("published_date")
        assert DateFlag.CLAIMED_DATE_UNTRUSTED in doc.date_flags
        assert DateFlag.UNPARSEABLE not in doc.date_flags
        assert (doc.published_on is None) == (item.get("published_date") is None)


def test_rfc2822_date_is_read() -> None:
    doc = parse_result(
        {
            "url": "https://a.example/x",
            "content": "hi",
            "published_date": "Sat, 01 Aug 2026 00:00:00 GMT",
        },
        fetched_at=FETCHED,
    )
    assert doc.published_on == date(2026, 8, 1)


def test_unreadable_date_is_flagged() -> None:
    doc = parse_result(
        {"url": "https://a.example/x", "content": "hi", "published_date": "someday soon"},
        fetched_at=FETCHED,
    )
    assert doc.published_on is None
    assert DateFlag.UNPARSEABLE in doc.date_flags
    assert DateFlag.CLAIMED_DATE_UNTRUSTED in doc.date_flags


def test_snippet_text_is_marked() -> None:
    doc = parse_result(
        {"url": "https://a.example/x", "content": "snip", "raw_content": None}, fetched_at=FETCHED
    )
    assert doc.text == "snip" and doc.meta["text_kind"] == "snippet"


def test_result_without_text_or_url_is_refused() -> None:
    with pytest.raises(ValueError):
        parse_result({"url": "https://a.example/x"}, fetched_at=FETCHED)
    with pytest.raises(ValueError):
        parse_result({"content": "x"}, fetched_at=FETCHED)


async def test_denied_host_result_is_dropped_linkedin() -> None:
    ex = next(
        (
            e
            for e in all_exchanges()
            if any("linkedin.com" in r["url"] for r in e.body_json["results"])
        ),
        None,
    )
    assert ex is not None, "the recorded fixtures contain a LinkedIn result"
    result = await sensor(replay_transport([ex], match_body=False)).search(
        SensorQuery(text=ex.request_json["query"])
    )
    assert all("linkedin.com" not in d.url for d in result.documents)
    assert any("deny list" in n for n in result.notes)


# ------------------------------------------------------------------ refusals and errors


async def test_as_of_is_refused_without_a_call() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(200, json={"results": []})

    with pytest.raises(ReplayUnsupported):
        await sensor(httpx.MockTransport(handler)).search(query(), as_of=FETCHED)
    assert not calls


async def test_missing_key_makes_no_call_and_names_the_variable() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(200, json={"results": []})

    s = Settings(_env_file=None, tavily_api_key=None)
    with pytest.raises(ConfigError, match="TAVILY_API_KEY"):
        await sensor(httpx.MockTransport(handler), s).search(query())
    assert not calls


async def test_call_cap_raises_before_the_extra_call() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(200, json={"results": []})

    s = sensor(httpx.MockTransport(handler), make_settings(tavily_max_calls_per_run=2))
    await s.search(query())
    await s.search(query())
    with pytest.raises(TavilyBudgetStopError):
        await s.search(query())
    assert len(calls) == 2


async def test_429_is_rate_limited_with_retry_after() -> None:
    with pytest.raises(SensorRateLimited) as info:
        await sensor(fixed(429, headers={"retry-after": "12"})).search(query())
    assert info.value.retry_after == 12.0


@pytest.mark.parametrize("status", [432, 433])
async def test_plan_limits_are_budget_stops_and_not_retried(status: int) -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(status)

    with pytest.raises(TavilyBudgetStopError) as info:
        await sensor(httpx.MockTransport(handler)).search(query())
    assert info.value.budget_stop is True
    assert len(calls) == 1


async def test_401_error_has_no_key() -> None:
    with pytest.raises(SensorError) as info:
        await sensor(fixed(401, json={"detail": {"error": SENTINEL}})).search(query())
    assert SENTINEL not in str(info.value)


async def test_key_never_leaks(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    ex = all_exchanges()[0]
    q = SensorQuery(text=ex.request_json["query"])
    result = await sensor(replay_transport([ex], match_body=False)).search(q)
    assert SENTINEL not in result.model_dump_json()
    for status in (400, 500, 401, 429, 432):
        with pytest.raises(SensorError) as info:
            await sensor(fixed(status)).search(query())
        assert SENTINEL not in str(info.value)
    assert SENTINEL not in caplog.text


def test_class_attributes() -> None:
    assert TavilySensor.name == "tavily"
    assert TavilySensor.enumerable is False
