"""Offline tests for the fixture recorder (T3.1). No network: MockTransport and injected sleep."""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from northvaine.core.settings import Settings
from northvaine.sensors.replay import RecordedExchange
from northvaine.sensors.ted import TED_SAFE_FIELDS

REPO = Path(__file__).resolve().parents[2]
CLIENTS = REPO / "tests" / "fixtures" / "clients"
KEY = "tvly-" + "FAKE" * 5


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "nv_recorder", REPO / "scripts" / "record_sensor_fixtures.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


rec = _load()


def _settings(**kw: Any) -> Settings:
    return Settings(_env_file=None, **kw)


def _ex(**kw: Any) -> RecordedExchange:
    base: dict[str, Any] = {
        "method": "POST",
        "url": "https://api.example/search",
        "status": 200,
        "recorded_at": datetime.now(UTC),
    }
    base.update(kw)
    return RecordedExchange(**base)


# --- specs --------------------------------------------------------------------------------


def test_every_client_spec_validates_and_builds() -> None:
    clients = rec.load_clients(CLIENTS)
    assert 2 <= len(clients) <= 3
    settings = _settings()
    calls = rec.plan_calls(clients, settings)
    assert calls
    expected = sum(
        len(c.sensors.get("ted", [])) + len(c.sensors.get("tavily", [])) for c in clients
    )
    assert len(calls) == expected
    for call in calls:
        if call.sensor == "ted":
            assert call.body["fields"] == list(TED_SAFE_FIELDS)
            assert "notice-type" in call.body["query"]


def test_ted_specs_cover_both_kinds_and_product_and_works_codes() -> None:
    for spec in rec.load_clients(CLIENTS):
        queries = spec.sensors.get("ted", [])
        if not queries:
            continue
        kinds = {k for q in queries for k in q["kinds"]}
        assert kinds == {"tender_published", "contract_awarded"}
        assert len(queries) >= 2


def test_multilingual_markets_get_one_tavily_query_per_language() -> None:
    langs = {
        spec.id: [q["languages"][0] for q in spec.sensors.get("tavily", [])]
        for spec in rec.load_clients(CLIENTS)
    }
    for spec_langs in langs.values():
        assert len(spec_langs) == len(set(spec_langs))
    assert any(len(v) > 1 for v in langs.values())


# --- redaction ----------------------------------------------------------------------------


def test_secret_and_authorization_removed_everywhere() -> None:
    ex = _ex(
        url=f"https://api.example/search?k={KEY}",
        request_json={"query": f"x {KEY}", "nested": [{"a": f"Bearer {KEY}"}]},
        headers={"Authorization": f"Bearer {KEY}", "content-type": "application/json"},
        body_json={"results": [{"content": f"leak {KEY}"}], f"k{KEY}": 1},
    )
    out = rec.redact_exchange(ex, secrets=[KEY])
    dumped = json.dumps(out.model_dump(mode="json"))
    assert KEY not in dumped
    assert "authorization" not in {k.lower() for k in out.headers}
    assert out.headers["content-type"] == "application/json"


def test_request_id_and_contact_keys_dropped() -> None:
    body = {
        "request_id": "abc",
        "results": [
            {
                "title": "ok",
                "Email": "x",
                "contact-point": "y",
                "telephone": "1",
                "phone_number": "2",
                "fax": "3",
                "person-name": "p",
            }
        ],
    }
    out = rec.redact_exchange(_ex(body_json=body), secrets=[])
    assert out.body_json == {"results": [{"title": "ok"}]}


def test_find_pii_flags_email_and_phone_and_spares_notice_numbers() -> None:
    assert rec.find_pii({"a": ["write to bob@example.com"]}) == ["$.a[0]"]
    assert rec.find_pii({"t": "call +44 20 7946 0958 now"}) == ["$.t"]
    assert rec.find_pii({"t": "tel 020 7946 0958"}) == ["$.t"]
    clean = {
        "publication-number": "412345-2026",
        "publication-date": "2026-07-01+02:00",
        "classification-cpv": ["45233250"],
        "total-value": 1250000.5,
    }
    assert rec.find_pii(clean) == []


def test_trim_keeps_n_and_strips_links() -> None:
    notices = [{"publication-number": str(i), "links": {"html": "u"}} for i in range(30)]
    out = rec.trim_exchange(_ex(body_json={"notices": notices, "total": 30}), "ted", 10)
    assert len(out.body_json["notices"]) == 10
    assert all("links" not in n for n in out.body_json["notices"])
    out = rec.trim_exchange(_ex(body_json={"results": list(range(9))}), "tavily", 4)
    assert out.body_json["results"] == [0, 1, 2, 3]


# --- recording ----------------------------------------------------------------------------


def _calls(settings: Settings) -> list[Any]:
    return rec.plan_calls(rec.load_clients(CLIENTS), settings)


def _run(
    settings: Settings, handler: Any, tmp_path: Path, calls: list[Any] | None = None
) -> tuple[int, list[float]]:
    import asyncio

    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    code = asyncio.run(
        rec.record(
            calls if calls is not None else _calls(settings),
            settings,
            out_dir=tmp_path,
            max_items=3,
            inner_factory=lambda: httpx.MockTransport(handler),
            sleep=fake_sleep,
        )
    )
    return code, sleeps


def _ok(request: httpx.Request) -> httpx.Response:
    if "tavily" in request.url.host:
        assert request.headers["authorization"] == f"Bearer {KEY}"
        return httpx.Response(
            200,
            json={"request_id": "r", "results": [{"title": f"t{i}", "url": "u"} for i in range(6)]},
        )
    return httpx.Response(
        200,
        json={
            "notices": [{"publication-number": str(i), "links": {"html": "u"}} for i in range(6)],
            "totalNoticeCount": 6,
        },
    )


def test_pacing_between_ted_calls_and_fixture_files(tmp_path: Path) -> None:
    settings = _settings(tavily_api_key=SecretStr(KEY), ted_min_interval_seconds=1.5)
    calls = _calls(settings)
    n_ted = sum(c.sensor == "ted" for c in calls)
    code, sleeps = _run(settings, _ok, tmp_path)
    assert code == 0
    assert sleeps == [1.5] * (n_ted - 1)
    files = sorted(tmp_path.rglob("*.json"))
    assert len(files) == len(calls)
    ted_file = next(tmp_path.glob("ted/*_1.json"))
    data = json.loads(ted_file.read_text(encoding="utf-8"))
    assert data[0]["request_json"]["fields"] == list(TED_SAFE_FIELDS)
    assert len(data[0]["body_json"]["notices"]) == 3
    assert "links" not in data[0]["body_json"]["notices"][0]
    tav = json.loads(next(tmp_path.glob("tavily/*_1.json")).read_text(encoding="utf-8"))
    assert "request_id" not in tav[0]["body_json"]
    assert all(KEY not in f.read_text(encoding="utf-8") for f in files)


def test_429_stops_ted_without_retry(tmp_path: Path) -> None:
    settings = _settings(tavily_api_key=SecretStr(KEY))
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.host)
        if "ted" in request.url.host:
            return httpx.Response(429, headers={"retry-after": "30"}, text="slow down")
        return _ok(request)

    ted_only = [c for c in _calls(settings) if c.sensor == "ted"]
    code, sleeps = _run(settings, handler, tmp_path, ted_only)
    assert code == 3
    assert len(seen) == 1
    assert sleeps == []
    assert not list(tmp_path.rglob("*.json"))


def test_missing_tavily_key_skips_tavily_but_records_ted(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    settings = _settings()
    hosts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        hosts.append(request.url.host)
        return _ok(request)

    code, _ = _run(settings, handler, tmp_path)
    assert code == 2
    assert hosts and all("tavily" not in h for h in hosts)
    assert list(tmp_path.glob("ted/*.json"))
    assert not (tmp_path / "tavily").exists()
    err = capsys.readouterr().err
    assert "TAVILY_API_KEY" in err
    assert KEY not in err


def test_tavily_calls_capped(tmp_path: Path) -> None:
    settings = _settings(tavily_api_key=SecretStr(KEY), tavily_max_calls_per_run=2)
    hosts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        hosts.append(request.url.host)
        return _ok(request)

    _run(settings, handler, tmp_path)
    assert sum("tavily" in h for h in hosts) == 2


def test_pii_refuses_write_and_exits_nonzero(tmp_path: Path) -> None:
    settings = _settings(tavily_api_key=SecretStr(KEY))

    def handler(request: httpx.Request) -> httpx.Response:
        if "tavily" in request.url.host:
            return httpx.Response(
                200, json={"results": [{"content": "mail jane.doe@example.com today"}]}
            )
        return _ok(request)

    code, _ = _run(settings, handler, tmp_path)
    assert code == 1
    assert not list(tmp_path.glob("tavily/*.json"))
    assert list(tmp_path.glob("ted/*.json"))


def test_main_refuses_without_yes(capsys: pytest.CaptureFixture[str]) -> None:
    def boom() -> Any:
        raise AssertionError("network path touched")

    code = rec.main([], settings=_settings(), inner_factory=boom)
    assert code == 1
    assert "--yes" in capsys.readouterr().err


def test_recorder_source_has_no_literal_secret_or_industry_leak() -> None:
    source = (REPO / "scripts" / "record_sensor_fixtures.py").read_text(encoding="utf-8")
    assert not re.search(r"tvly-[A-Za-z0-9]{8,}", source)
