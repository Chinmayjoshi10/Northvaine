"""TED sensor: parsing, availability, pagination, pacing and errors (T3.4). No network."""

from __future__ import annotations

import json
import re
from datetime import UTC, date, datetime
from pathlib import Path

import httpx
import pytest

from northvaine.core.settings import Settings
from northvaine.sensors import ted
from northvaine.sensors.base import (
    DateFlag,
    SensorError,
    SensorQuery,
    SensorRateLimited,
)
from northvaine.sensors.replay import load_exchanges, replay_transport
from northvaine.sensors.ted import TedSensor, parse_notice, render_notice_text

ROOT = Path(__file__).parent.parent
FIXTURES = ROOT / "fixtures" / "sensors" / "ted"
CLIENTS = ROOT / "fixtures" / "clients"
SETTINGS = Settings(_env_file=None)
FETCHED = datetime(2026, 10, 4, 9, 0, tzinfo=UTC)
PII_KEY = re.compile(r"email|tel|fax|person|contact", re.IGNORECASE)
URL = SETTINGS.ted_api_url


async def no_sleep(seconds: float) -> None:
    return None


def recorded_records() -> list[dict]:
    records = []
    for path in sorted(FIXTURES.glob("*.json")):
        for exchange in json.loads(path.read_text(encoding="utf-8")):
            records.extend(exchange["body_json"]["notices"])
    return records


def record(number="100-2026", **kw) -> dict:
    base = {
        "publication-number": number,
        "notice-type": "cn-standard",
        "notice-version": 1,
        "procedure-identifier": f"proc-{number}",
        "publication-date": "2026-06-01+02:00",
    }
    base.update(kw)
    return base


def keys_of(value) -> list[str]:
    found = []
    if isinstance(value, dict):
        for k, v in value.items():
            found.append(k)
            found.extend(keys_of(v))
    elif isinstance(value, list):
        for v in value:
            found.extend(keys_of(v))
    return found


def query(**kw) -> SensorQuery:
    kw.setdefault("kinds", ["tender_published"])
    return SensorQuery(**kw)


def mock_client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def pages_handler(pages: list[list[dict]], total: int, calls: list[dict] | None = None):
    """A fake TED: serves `pages` by the requested page number (empty beyond the list)."""

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if calls is not None:
            calls.append(body)
        index = body["page"] - 1
        notices = pages[index] if index < len(pages) else []
        return httpx.Response(200, json={"notices": notices, "totalNoticeCount": total})

    return handler


# ----------------------------------------------------------------------------- replay


def client_specs() -> list[tuple[str, dict]]:
    specs = []
    for path in sorted(CLIENTS.glob("*.json")):
        spec = json.loads(path.read_text(encoding="utf-8"))
        for q in spec.get("sensors", {}).get("ted", []):
            specs.append((spec["id"], q))
    return specs


def test_every_sample_client_query_is_served_by_the_recordings():
    specs = client_specs()
    assert len(specs) >= 8
    by_client: dict[str, list] = {}
    for client_id, _ in specs:
        by_client.setdefault(client_id, [])
    for client_id in by_client:
        for path in sorted(FIXTURES.glob(f"{client_id}_*.json")):
            by_client[client_id].extend(load_exchanges(path))

    async def run() -> int:
        count = 0
        for client_id, q in specs:
            transport = replay_transport(by_client[client_id], match_body=True)
            async with httpx.AsyncClient(transport=transport) as http:
                sensor = TedSensor(client=http, settings=SETTINGS, sleep=no_sleep)
                result = await sensor.search(SensorQuery(**q))  # an unmatched body would raise
            assert result.documents
            assert result.enumerable is True
            count += 1
        return count

    import asyncio

    assert asyncio.run(run()) == len(specs)


# ----------------------------------------------------------------------------- parsing


def test_parse_every_recorded_notice():
    records = recorded_records()
    assert len(records) >= 60
    for rec in records:
        doc = parse_notice(rec, fetched_at=FETCHED, settings=SETTINGS)
        number = rec["publication-number"]
        assert doc.source == "ted"
        assert doc.external_id == number
        assert doc.group_key == rec["procedure-identifier"]
        assert doc.url == f"https://ted.europa.eu/en/notice/{number}/html"
        assert doc.text == render_notice_text(rec)
        assert doc.text.startswith(f"Notice: {number}")
        assert doc.meta["schema_ver"] == 1
        assert doc.meta["notice_type"] == rec["notice-type"]
        assert doc.meta["notice_version"] == rec["notice-version"]
        assert doc.meta["raw_dates"]["publication"] == rec["publication-date"]
        assert not [k for k in keys_of(doc.meta) if PII_KEY.search(k)]
        json.dumps(doc.meta)  # jsonb-safe


def test_text_is_byte_identical_for_the_same_record():
    for rec in recorded_records():
        assert (
            render_notice_text(rec).encode()
            == render_notice_text(json.loads(json.dumps(rec))).encode()
        )


def test_text_keeps_the_quotable_facts_and_every_language():
    rec = record(
        **{
            "notice-title": {"eng": "Chillers", "deu": "Kaelteanlagen"},
            "buyer-name": {"deu": ["Stadt A", "Stadt A"]},
            "winner-name": {"deu": ["Firma B"]},
            "classification-cpv": ["42500000", "42500000"],
            "total-value": 1234.5,
        }
    )
    text = render_notice_text(rec)
    for fragment in (
        "Title [deu]: Kaelteanlagen",
        "Title [eng]: Chillers",
        "Buyer [deu]: Stadt A",
        "Winner [deu]: Firma B",
        "CPV: 42500000",
        "Total value: 1234.50",
        "Published: 2026-06-01+02:00",
    ):
        assert fragment in text
    assert text.count("Stadt A") == 1


def test_meta_of_an_award_dedupes_per_lot_winners_and_pairs_countries():
    rec = record(
        **{
            "notice-type": "can-standard",
            "winner-name": {"deu": ["Firma B", "Firma B", "Firma C"]},
            "winner-country": ["DEU", "DEU", "AUT"],
            "winner-decision-date": ["2026-05-29+02:00"] * 3,
            "buyer-name": {"deu": ["Stadt A"]},
        }
    )
    meta = parse_notice(rec, fetched_at=FETCHED, settings=SETTINGS).meta
    assert meta["notice_kind"] == "contract_awarded"
    assert meta["winners"] == [
        {"name": "Firma B", "country": "DEU"},
        {"name": "Firma C", "country": "AUT"},
    ]
    assert meta["winner_decision_dates"] == ["2026-05-29"]
    assert meta["raw_dates"]["winner_decisions"] == ["2026-05-29+02:00"]
    assert meta["buyers"] == ["Stadt A"]


def test_total_value_zero_is_not_stated_not_a_zero_contract():
    doc = parse_notice(record(**{"total-value": 0}), fetched_at=FETCHED, settings=SETTINGS)
    assert doc.meta["value"] is None
    assert "total_value_zero_read_as_not_stated" in doc.meta["notes"]
    assert "Total value" not in doc.text


def test_legacy_record_without_winner_or_title_fields_parses():
    doc = parse_notice(
        {"publication-number": "1-2026", "publication-date": "2026-06-01"},
        fetched_at=FETCHED,
        settings=SETTINGS,
    )
    assert doc.title is None
    assert doc.group_key is None
    assert doc.meta["winners"] == []
    assert doc.meta["notice_kind"] is None


def test_unmapped_notice_type_has_no_kind():
    doc = parse_notice(record(**{"notice-type": "pin-only"}), fetched_at=FETCHED, settings=SETTINGS)
    assert doc.meta["notice_kind"] is None
    assert doc.meta["notice_type"] == "pin-only"


def test_record_without_publication_number_is_refused():
    with pytest.raises(ValueError):
        parse_notice({"notice-type": "cn-standard"}, fetched_at=FETCHED, settings=SETTINGS)


def test_dates_are_flagged_not_corrected():
    rec = record(**{"deadline-receipt-request": ["2026-04-30T12:00:00+02:00"]})
    doc = parse_notice(rec, fetched_at=FETCHED, settings=SETTINGS)
    assert DateFlag.DEADLINE_BEFORE_PUBLICATION in doc.date_flags
    assert doc.meta["deadlines"] == ["2026-04-30"]
    assert doc.meta["raw_dates"]["deadlines"] == ["2026-04-30T12:00:00+02:00"]


def test_unparseable_and_missing_publication():
    junk = parse_notice(
        record(**{"publication-date": "soon"}), fetched_at=FETCHED, settings=SETTINGS
    )
    assert DateFlag.UNPARSEABLE in junk.date_flags
    assert DateFlag.MISSING_PUBLICATION in junk.date_flags
    assert junk.published_on is None and junk.available_at is None
    gone = record()
    del gone["publication-date"]
    doc = parse_notice(gone, fetched_at=FETCHED, settings=SETTINGS)
    assert doc.date_flags == [DateFlag.MISSING_PUBLICATION]


# ----------------------------------------------------------------------------- availability


def test_available_at_comes_only_from_publication_date():
    rec = record(
        **{
            "deadline-receipt-request": ["2027-01-01T12:00:00+01:00"],
            "winner-decision-date": ["2026-01-01+01:00"],
        }
    )
    doc = parse_notice(rec, fetched_at=FETCHED, settings=SETTINGS)
    assert doc.published_on == date(2026, 6, 1)
    assert doc.available_at == datetime(2026, 6, 2, tzinfo=UTC)


def test_lag_setting_is_used():
    settings = Settings(_env_file=None, ted_availability_lag_days=3)
    doc = parse_notice(record(), fetched_at=FETCHED, settings=settings)
    assert doc.available_at == datetime(2026, 6, 4, tzinfo=UTC)


def test_notice_fetched_on_its_publication_day_is_not_yet_available():
    fetched = datetime(2026, 6, 1, 18, 0, tzinfo=UTC)
    doc = parse_notice(record(), fetched_at=fetched, settings=SETTINGS)
    assert doc.available_at > fetched


def test_changed_notice_is_dated_by_its_own_publication_date():
    # Synthetic: the recordings hold no notice-version > 1 (PF2 found one only in a later probe).
    rec = record(
        **{"notice-version": 3, "notice-type": "can-modif", "publication-date": "2026-09-02+02:00"}
    )
    doc = parse_notice(rec, fetched_at=FETCHED, settings=SETTINGS)
    assert doc.published_on == date(2026, 9, 2)
    assert doc.available_at == datetime(2026, 9, 3, tzinfo=UTC)
    assert doc.meta["notice_version"] == 3
    assert "changed_notice_original_window_lost" in doc.meta["notes"]


async def test_as_of_drops_documents_not_yet_available_and_counts_them():
    pages = [
        [record("1-2026", **{"publication-date": "2026-05-30"}), record("2-2026"), record("3-2026")]
    ]
    async with mock_client(pages_handler(pages, total=3)) as http:
        sensor = TedSensor(client=http, settings=SETTINGS, sleep=no_sleep)
        as_of = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)  # 2026-06-01 notices open 2026-06-02
        result = await sensor.search(query(), as_of=as_of)
    assert [d.external_id for d in result.documents] == ["1-2026"]
    assert any("dropped 2 notice(s)" in n for n in result.notes)
    assert all(d.available_at <= as_of for d in result.documents)


# ----------------------------------------------------------------------------- pagination


async def test_dedupes_on_publication_number_and_version():
    page = [
        record("1-2026"),
        record("1-2026"),
        record("1-2026", **{"notice-version": 2}),
        record("2-2026"),
    ]
    async with mock_client(pages_handler([page], total=4)) as http:
        sensor = TedSensor(client=http, settings=SETTINGS, sleep=no_sleep)
        result = await sensor.search(query())
    assert [(d.external_id, d.meta["notice_version"]) for d in result.documents] == [
        ("1-2026", 1),
        ("1-2026", 2),
        ("2-2026", 1),
    ]


async def test_stops_on_an_empty_page():
    calls: list[dict] = []
    pages = [[record("1-2026"), record("2-2026")]]
    handler = pages_handler(pages, total=99, calls=calls)  # total is never reached
    async with mock_client(handler) as http:
        sensor = TedSensor(client=http, settings=SETTINGS, sleep=no_sleep)
        result = await sensor.search(query(max_results=100))
    assert [d.external_id for d in result.documents] == ["1-2026", "2-2026"]
    assert [c["page"] for c in calls] == [1, 2]
    assert result.next_cursor is None and result.truncated is False


async def test_stops_when_unique_notices_reach_total_count():
    calls: list[dict] = []
    pages = [[record(f"{i}-2026") for i in range(5)], [record(f"{i}-2026") for i in range(5, 8)]]
    async with mock_client(pages_handler(pages, total=8, calls=calls)) as http:
        sensor = TedSensor(client=http, settings=SETTINGS, sleep=no_sleep)
        result = await sensor.search(query(max_results=25))
    assert len(result.documents) == 8
    assert [c["page"] for c in calls] == [1, 2]  # page 2 reaches the total: no empty probe page
    assert result.next_cursor is None and result.truncated is False


async def test_a_full_page_at_max_results_is_truncated_with_a_next_cursor():
    first = [record(f"{i}-2026") for i in range(250)]
    async with mock_client(pages_handler([first], total=300)) as http:
        sensor = TedSensor(client=http, settings=SETTINGS, sleep=no_sleep)
        result = await sensor.search(query(max_results=250))
    assert len(result.documents) == 250
    assert result.truncated is True
    assert result.next_cursor == "2"


async def test_stops_at_max_results_sets_truncated_and_returns_the_next_page_cursor():
    calls: list[dict] = []
    pages = [[record(f"{i}-2026") for i in range(3)], [record(f"{i}-2026") for i in range(3, 6)]]
    async with mock_client(pages_handler(pages, total=6, calls=calls)) as http:
        sensor = TedSensor(client=http, settings=SETTINGS, sleep=no_sleep)
        first = await sensor.search(query(max_results=3))
        assert first.truncated is True and first.next_cursor == "2"
        second = await sensor.search(query(max_results=3), cursor=first.next_cursor)
    assert [c["page"] for c in calls] == [1, 2]
    assert [d.external_id for d in second.documents] == ["3-2026", "4-2026", "5-2026"]
    assert second.next_cursor is None and second.truncated is False


async def test_bad_cursor_is_refused():
    async with mock_client(pages_handler([], total=0)) as http:
        sensor = TedSensor(client=http, settings=SETTINGS, sleep=no_sleep)
        with pytest.raises(ValueError):
            await sensor.search(query(), cursor="abc")


# ----------------------------------------------------------------------------- pacing and errors


async def test_waits_between_its_own_calls():
    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    pages = [[record("1-2026")], [record("2-2026")]]
    async with mock_client(pages_handler(pages, total=2)) as http:
        sensor = TedSensor(client=http, settings=SETTINGS, sleep=fake_sleep)
        await sensor.search(query(max_results=1))
        assert sleeps == []  # the first call never waits
        await sensor.search(query(max_results=1), cursor="2")
    assert len(sleeps) == 1
    assert 0 < sleeps[0] <= SETTINGS.ted_min_interval_seconds
    assert sleeps[0] > SETTINGS.ted_min_interval_seconds - 1.0


async def test_html_429_without_retry_after_never_parses_json():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429,
            headers={"content-type": "text/html"},
            content=b"<html>429 Too Many Requests</html>",
        )

    async with mock_client(handler) as http:
        sensor = TedSensor(client=http, settings=SETTINGS, sleep=no_sleep)
        with pytest.raises(SensorRateLimited) as info:
            await sensor.search(query())
    assert info.value.retry_after is None


async def test_429_with_retry_after_carries_it():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"retry-after": "7"}, content=b"slow down")

    async with mock_client(handler) as http:
        sensor = TedSensor(client=http, settings=SETTINGS, sleep=no_sleep)
        with pytest.raises(SensorRateLimited) as info:
            await sensor.search(query())
    assert info.value.retry_after == 7.0


async def test_json_400_raises_sensor_error_with_the_ted_error_type():
    def handler(request: httpx.Request) -> httpx.Response:
        body = {"message": "bad query", "error": {"type": "QUERY_SYNTAX_ERROR"}}
        return httpx.Response(400, json=body)

    async with mock_client(handler) as http:
        sensor = TedSensor(client=http, settings=SETTINGS, sleep=no_sleep)
        with pytest.raises(SensorError, match="QUERY_SYNTAX_ERROR") as info:
            await sensor.search(query())
    assert not isinstance(info.value, SensorRateLimited)


async def test_sends_exactly_the_frozen_request_body():
    calls: list[dict] = []
    q = query(codes=["cpv:12345678"], countries=["FR"], published_from=date(2026, 2, 1))
    async with mock_client(pages_handler([[record()]], total=1, calls=calls)) as http:
        sensor = TedSensor(client=http, settings=SETTINGS, sleep=no_sleep)
        await sensor.search(q)
    assert calls == [ted.build_request(q, page=1, settings=SETTINGS)]
