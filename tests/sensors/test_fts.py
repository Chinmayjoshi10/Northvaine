"""UK Find a Tender sensor: request mapping, parsing, rendering, availability, privacy, replay.
No network: every HTTP exchange is a recorded fixture or a hand-built response."""

from __future__ import annotations

import json
import re
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest

from northvaine.core.models import EventType
from northvaine.core.settings import Settings
from northvaine.radar.ledger import evidence_document_from_sensor
from northvaine.radar.structured import structured_evidence
from northvaine.sensors import fts
from northvaine.sensors.base import (
    DateFlag,
    Sensor,
    SensorError,
    SensorQuery,
    SensorRateLimited,
)
from northvaine.sensors.fts import FtsSensor, parse_release, render_release_text
from northvaine.sensors.replay import load_exchanges, replay_transport

FIXTURES = Path(__file__).parent.parent / "fixtures" / "sensors" / "fts"
SETTINGS = Settings(_env_file=None)
FETCHED = datetime(2026, 10, 8, 9, 0, tzinfo=UTC)
EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
BOTH = [EventType.TENDER_PUBLISHED, EventType.CONTRACT_AWARDED]
DAY = date(2026, 10, 2)


async def no_sleep(seconds: float) -> None:
    return None


def recorded_releases() -> dict[str, dict[str, Any]]:
    releases: dict[str, dict[str, Any]] = {}
    for path in sorted(FIXTURES.glob("*.json")):
        for exchange in json.loads(path.read_text(encoding="utf-8")):
            for release in exchange["body_json"]["releases"]:
                releases[release["id"]] = release
    return releases


RELEASES = recorded_releases()


def release(**kw: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "ocid": "ocds-test-000001",
        "id": "000001-2026",
        "tag": ["tender"],
        "date": "2026-06-01T10:00:00+01:00",
        "language": "en",
        "buyer": {"id": "B1", "name": "Example Council"},
        "parties": [{"id": "B1", "name": "Example Council", "address": {"country": "GB"}}],
        "tender": {"title": "Example works", "tenderPeriod": {"endDate": "2026-07-01T12:00:00Z"}},
    }
    base.update(kw)
    return base


def client_for(exchanges: list, sleeps: list[float] | None = None) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=replay_transport(exchanges, match_body=False))


def any_url_client(name: str = "both_kinds_1.json") -> httpx.AsyncClient:
    """Serves the first recorded page for whatever URL is asked (limit differs per query)."""
    body = load_exchanges(FIXTURES / name)[0].body_json
    body = {**body, "links": {}}  # one page only

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=body)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def query(**kw: Any) -> SensorQuery:
    base: dict[str, Any] = {
        "kinds": BOTH,
        "countries": ["GB"],
        "published_from": DAY,
        "published_to": DAY,
        "max_results": 8,
    }
    base.update(kw)
    return SensorQuery(**base)


# ------------------------------------------------------------------------ request mapping


def test_build_request_maps_window_and_limit() -> None:
    params = fts.build_request(query(), settings=SETTINGS)
    assert list(params) == ["limit", "updatedFrom", "updatedTo"]
    assert params == {
        "limit": "8",
        "updatedFrom": "2026-10-02T00:00:00",
        "updatedTo": "2026-10-02T23:59:59",
    }


def test_build_request_never_uses_the_stages_filter() -> None:
    params = fts.build_request(query(codes=["cpv:45000000"]), settings=SETTINGS)
    assert "stages" not in params
    assert "45000000" not in json.dumps(params)  # cpv is applied after the page is read


def test_build_request_caps_limit_and_passes_the_cursor() -> None:
    params = fts.build_request(query(max_results=250), cursor="abc=", settings=SETTINGS)
    assert params["limit"] == "100"
    assert params["cursor"] == "abc="
    assert list(params)[-1] == "cursor"


def test_build_request_as_of_bounds_the_window_by_the_availability_lag() -> None:
    as_of = datetime(2026, 10, 2, 12, 0, tzinfo=UTC)
    params = fts.build_request(
        query(published_from=None, published_to=date(2026, 10, 9)), as_of=as_of, settings=SETTINGS
    )
    assert params["updatedTo"] == "2026-10-01T23:59:59"
    early = fts.build_request(
        query(published_from=None, published_to=date(2026, 9, 1)), as_of=as_of, settings=SETTINGS
    )
    assert early["updatedTo"] == "2026-09-01T23:59:59"


def test_build_request_without_dates_omits_the_window() -> None:
    params = fts.build_request(query(published_from=None, published_to=None), settings=SETTINGS)
    assert params == {"limit": "8"}


def test_build_request_rejects_a_query_with_no_mappable_kind() -> None:
    with pytest.raises(ValueError, match="no query kind"):
        fts.build_request(query(kinds=[EventType.REORDER_DUE]), settings=SETTINGS)
    with pytest.raises(ValueError, match="no query kind"):
        fts.build_request(query(kinds=[]), settings=SETTINGS)


def test_build_request_needs_a_timezone_aware_as_of() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        fts.build_request(query(), as_of=datetime(2026, 10, 2), settings=SETTINGS)


def test_module_holds_no_industry_words() -> None:
    source = Path(fts.__file__).read_text(encoding="utf-8").lower()
    for word in ("stone", "freight", "granite", "cold-chain", "coldchain", "packaging"):
        assert word not in source


# ------------------------------------------------------------------------ rendering


def test_a_tender_renders_ted_style_lines() -> None:
    text = render_release_text(RELEASES["093572-2026"], settings=SETTINGS)
    assert text.split("\n") == [
        "Notice: 093572-2026 (UK4)",
        "Procedure: ocds-h6vhtk-078036",
        "Published: 2026-10-02T19:02:31+01:00",
        "Title [eng]: Football Delivery Partner - Redcar and Cleveland College",
        "Buyer [eng]: The Education Training Collective",
        "Buyer country: GB",
        "CPV: 80000000",
        "Deadline: 2026-10-16T12:00:00+01:00",
        "Estimated value (lot): 75000.00 GBP",
    ]


def test_an_award_renders_winner_value_and_signing_lines() -> None:
    text = render_release_text(RELEASES["093575-2026"], settings=SETTINGS)
    lines = text.split("\n")
    assert "Winner [eng]: Jeakins Weir Ltd." in lines
    assert "Winner country: GB" in lines
    assert "Total value: 64470.68 GBP" in lines
    assert "Contract signed: 2026-10-01T00:00:00+01:00" in lines
    assert not any(line.startswith("Winner decision date") for line in lines)


def test_rendering_is_deterministic() -> None:
    for rel in RELEASES.values():
        assert render_release_text(rel, settings=SETTINGS) == render_release_text(
            json.loads(json.dumps(rel)), settings=SETTINGS
        )


def test_a_framework_does_not_state_a_summed_total() -> None:
    doc = parse_release(RELEASES["093562-2026"], fetched_at=FETCHED, settings=SETTINGS)
    assert not any(line.startswith("Total value") for line in doc.text.split("\n"))
    assert doc.meta["value"] is None
    assert "multiple_contract_values_total_not_stated" in doc.meta["notes"]


def test_winners_are_deduplicated_and_cpv_is_unique() -> None:
    doc = parse_release(RELEASES["093562-2026"], fetched_at=FETCHED, settings=SETTINGS)
    names = [w["name"] for w in doc.meta["winners"]]
    assert len(names) == len(set(names))
    assert len(doc.meta["cpv_codes"]) == len(set(doc.meta["cpv_codes"]))


def test_title_falls_back_to_the_contract_title() -> None:
    rel = release(tag=["award"], tender={}, contracts=[{"title": "Contract title"}])
    assert parse_release(rel, fetched_at=FETCHED, settings=SETTINGS).title == "Contract title"


def test_free_text_description_is_not_rendered() -> None:
    rel = release(tender={"title": "T", "description": "SECRET-DESCRIPTION call 01234 567 890"})
    assert "SECRET-DESCRIPTION" not in render_release_text(rel, settings=SETTINGS)


# ------------------------------------------------------------------------ parsing and meta


def test_meta_uses_the_ted_keys_structured_evidence_reads() -> None:
    doc = parse_release(RELEASES["093572-2026"], fetched_at=FETCHED, settings=SETTINGS)
    for key in (
        "schema_ver",
        "notice_kind",
        "buyers",
        "buyer_countries",
        "winners",
        "cpv_codes",
        "deadlines",
        "estimated_values",
        "value",
        "raw_dates",
    ):
        assert key in doc.meta
    assert doc.meta["schema_ver"] == 1
    assert doc.meta["notice_kind"] == "tender_published"
    assert doc.meta["buyers"] == ["The Education Training Collective"]
    assert doc.meta["deadlines"] == ["2026-10-16"]
    assert doc.meta["raw_dates"]["publication"] == "2026-10-02T19:02:31+01:00"
    assert doc.group_key == "ocds-h6vhtk-078036"
    assert doc.external_id == "093572-2026"
    assert doc.url == "https://www.find-tender.service.gov.uk/Notice/093572-2026"
    assert doc.source == "fts"


def test_award_meta_carries_winners_and_value() -> None:
    doc = parse_release(RELEASES["093575-2026"], fetched_at=FETCHED, settings=SETTINGS)
    assert doc.meta["notice_kind"] == "contract_awarded"
    assert doc.meta["winners"] == [{"name": "Jeakins Weir Ltd.", "country": "GB"}]
    assert doc.meta["value"] == pytest.approx(64470.68)
    assert doc.meta["currency"] == "GBP"
    assert doc.meta["contract_signed_dates"] == ["2026-10-01"]
    assert doc.meta["winner_decision_dates"] == []


@pytest.mark.parametrize(
    ("tags", "kind"),
    [
        (["tender"], EventType.TENDER_PUBLISHED),
        (["tenderUpdate"], EventType.TENDER_PUBLISHED),
        (["award", "contract"], EventType.CONTRACT_AWARDED),
        (["awardUpdate", "contractUpdate"], EventType.CONTRACT_AWARDED),
        (["planning"], None),
        (["tenderCancellation"], None),
        (["contractTermination"], None),
    ],
)
def test_tags_map_to_generic_kinds(tags: list[str], kind: EventType | None) -> None:
    assert fts.release_kind({"tag": tags}) == kind


def test_a_release_without_an_id_is_rejected() -> None:
    with pytest.raises(ValueError, match="no id"):
        parse_release(release(id=None), fetched_at=FETCHED, settings=SETTINGS)


# ------------------------------------------------------------------------ available_at and dates


def test_available_at_is_the_day_after_the_publication_date() -> None:
    doc = parse_release(RELEASES["093572-2026"], fetched_at=FETCHED, settings=SETTINGS)
    assert doc.published_on == date(2026, 10, 2)
    assert doc.available_at == datetime(2026, 10, 3, tzinfo=UTC)
    assert doc.date_flags == []


def test_available_at_ignores_later_dated_fields() -> None:
    rel = release(
        tag=["award"],
        contracts=[{"dateSigned": "2027-01-01T00:00:00Z", "period": {"endDate": "2030-01-01"}}],
    )
    doc = parse_release(rel, fetched_at=FETCHED, settings=SETTINGS)
    assert doc.available_at == datetime(2026, 6, 2, tzinfo=UTC)


def test_a_deadline_before_publication_is_flagged_not_corrected() -> None:
    rel = release(tender={"title": "T", "tenderPeriod": {"endDate": "2026-05-01T12:00:00Z"}})
    doc = parse_release(rel, fetched_at=FETCHED, settings=SETTINGS)
    assert DateFlag.DEADLINE_BEFORE_PUBLICATION in doc.date_flags
    assert doc.meta["deadlines"] == ["2026-05-01"]
    assert "Deadline: 2026-05-01T12:00:00Z" in doc.text


def test_signing_after_publication_is_flagged() -> None:
    rel = release(tag=["award"], contracts=[{"dateSigned": "2026-08-01T00:00:00Z"}])
    doc = parse_release(rel, fetched_at=FETCHED, settings=SETTINGS)
    assert DateFlag.DECISION_AFTER_PUBLICATION in doc.date_flags


def test_several_signing_dates_are_flagged() -> None:
    doc = parse_release(RELEASES["093562-2026"], fetched_at=FETCHED, settings=SETTINGS)
    assert DateFlag.MULTIPLE_VALUES in doc.date_flags


def test_a_missing_publication_date_gives_no_availability() -> None:
    doc = parse_release(release(date=None), fetched_at=FETCHED, settings=SETTINGS)
    assert doc.available_at is None
    assert DateFlag.MISSING_PUBLICATION in doc.date_flags


def test_an_unreadable_publication_date_is_flagged_unparseable() -> None:
    doc = parse_release(release(date="soon"), fetched_at=FETCHED, settings=SETTINGS)
    assert doc.available_at is None
    assert DateFlag.UNPARSEABLE in doc.date_flags


# ------------------------------------------------------------------------ privacy


def test_natural_persons_are_withheld_in_suppliers_and_buyer() -> None:
    rel = release(
        tag=["award"],
        buyer={"id": "B1", "name": "Hans Beispiel Inhaber"},
        awards=[
            {
                "suppliers": [
                    {"id": "S1", "name": "Max Muster e.K."},
                    {"id": "S2", "name": "Muster Holdings Limited"},
                ]
            }
        ],
    )
    doc = parse_release(rel, fetched_at=FETCHED, settings=SETTINGS)
    assert "Max Muster" not in doc.text and "Hans Beispiel" not in doc.text
    assert "Max Muster" not in json.dumps(doc.meta)
    assert "[natural person, name withheld" in doc.text
    assert "Muster Holdings Limited" in doc.text


def test_contact_points_never_reach_a_document() -> None:
    rel = release(
        parties=[
            {
                "id": "B1",
                "name": "Example Council",
                "address": {"country": "GB", "streetAddress": "1 Private Lane"},
                "contactPoint": {
                    "name": "Jane Person",
                    "email": "jane.person@example.org",
                    "telephone": "+44 20 7946 0000",
                },
            }
        ],
        tender={"title": "Write to jane.person@example.org", "description": "Call 020 7946 0000"},
    )
    doc = parse_release(rel, fetched_at=FETCHED, settings=SETTINGS)
    blob = doc.text + json.dumps(doc.meta) + (doc.title or "")
    for secret in ("Jane Person", "jane.person@", "7946", "Private Lane"):
        assert secret not in blob


def test_recorded_fixtures_hold_no_email_phone_or_contact_keys() -> None:
    phone = re.compile(r"(?<!\d)(?:\+\d[\d ()-]{7,}\d|0\d{2,4}[ -]?\d{3,4}[ -]?\d{3,4})(?!\d)")

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                lowered = key.lower()
                assert "contactpoint" not in lowered
                assert lowered not in {"email", "telephone", "faxnumber", "streetaddress"}
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)
        elif isinstance(value, str):
            assert not EMAIL.search(value)
            if " " in value:  # ids and urls hold no whitespace
                assert not phone.search(value)

    for path in sorted(FIXTURES.glob("*.json")):
        raw = path.read_text(encoding="utf-8")
        assert not EMAIL.search(raw)
        walk(json.loads(raw))


def test_every_recorded_document_is_free_of_emails_and_contact_words() -> None:
    assert RELEASES
    for rel in RELEASES.values():
        doc = parse_release(rel, fetched_at=FETCHED, settings=SETTINGS)
        assert not EMAIL.search(doc.text + json.dumps(doc.meta))
        assert "contact" not in json.dumps(sorted(doc.meta))


def test_the_recorded_sole_traders_are_placeholders() -> None:
    doc = parse_release(RELEASES["093562-2026"], fetched_at=FETCHED, settings=SETTINGS)
    names = [w["name"] for w in doc.meta["winners"]]
    assert "[natural person redacted 1]" in names


# ------------------------------------------------------------------------ replay through the sensor


def test_the_sensor_satisfies_the_protocol() -> None:
    sensor = FtsSensor(settings=SETTINGS)
    assert isinstance(sensor, Sensor)
    assert (sensor.name, sensor.enumerable) == ("fts", True)


@pytest.mark.asyncio
async def test_first_page_replays_into_documents_with_a_cursor() -> None:
    exchanges = load_exchanges(FIXTURES / "both_kinds_1.json")
    async with client_for(exchanges) as client:
        result = await FtsSensor(client=client, settings=SETTINGS, sleep=no_sleep).search(query())
    assert result.enumerable is True
    assert [d.external_id for d in result.documents] == [
        "093576-2026",
        "093575-2026",
        "093574-2026",
        "093573-2026",
        "093572-2026",
        "093571-2026",
        "093570-2026",
        "093569-2026",
    ]
    assert result.truncated is True
    assert result.next_cursor
    assert all(d.source == "fts" and d.available_at for d in result.documents)


@pytest.mark.asyncio
async def test_cursor_continues_and_drops_other_stages() -> None:
    first = load_exchanges(FIXTURES / "both_kinds_1.json")
    async with client_for(first) as client:
        page1 = await FtsSensor(client=client, settings=SETTINGS, sleep=no_sleep).search(query())
    exchanges = load_exchanges(FIXTURES / "both_kinds_2.json")
    async with client_for(exchanges) as client:
        page2 = await FtsSensor(client=client, settings=SETTINGS, sleep=no_sleep).search(
            query(), cursor=page1.next_cursor
        )
    ids = [d.external_id for d in page2.documents]
    assert len(ids) == 8
    assert "093565-2026" not in ids  # tenderCancellation
    assert "093556-2026" not in ids and "093555-2026" not in ids  # planning
    assert not set(ids) & {d.external_id for d in page1.documents}
    assert any("not tender or award" in note for note in page2.notes)
    assert page2.truncated is True and page2.next_cursor is None  # cut at max_results


@pytest.mark.asyncio
async def test_kind_filter_keeps_only_awards() -> None:
    async with any_url_client() as client:
        result = await FtsSensor(client=client, settings=SETTINGS, sleep=no_sleep).search(
            query(kinds=[EventType.CONTRACT_AWARDED], max_results=3)
        )
    assert len(result.documents) <= 3
    assert {d.meta["notice_kind"] for d in result.documents} == {"contract_awarded"}


@pytest.mark.asyncio
async def test_cpv_codes_filter_documents() -> None:
    async with any_url_client() as client:
        result = await FtsSensor(client=client, settings=SETTINGS, sleep=no_sleep).search(
            query(codes=["cpv:80000000"], max_results=1)
        )
    assert [d.external_id for d in result.documents] == ["093572-2026"]


@pytest.mark.asyncio
async def test_as_of_drops_documents_not_yet_available() -> None:
    as_of = datetime(2026, 10, 2, 23, 0, tzinfo=UTC)
    async with any_url_client() as client:
        # the replayed server ignores the window, so the sensor's own gate must hold
        sensor = FtsSensor(client=client, settings=SETTINGS, sleep=no_sleep)
        early = query(published_from=None, published_to=date(2026, 10, 1))
        result = await sensor.search(early, as_of=as_of)
    assert result.documents == []
    assert any("after as_of" in note for note in result.notes)


@pytest.mark.asyncio
async def test_a_non_gb_country_query_makes_no_request() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no request expected")

    async with httpx.AsyncClient(transport=httpx.MockTransport(refuse)) as client:
        result = await FtsSensor(client=client, settings=SETTINGS).search(query(countries=["DE"]))
    assert result.documents == [] and "GB only" in result.notes[0]


@pytest.mark.asyncio
async def test_the_sensor_sends_no_credentials_and_only_known_parameters() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"releases": []})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await FtsSensor(client=client, settings=SETTINGS, sleep=no_sleep).search(query())
    request = seen[0]
    assert request.method == "GET"
    assert str(request.url).startswith(fts.FTS_API_URL + "?limit=8&updatedFrom=")
    assert "authorization" not in request.headers


# ------------------------------------------------------------------------ errors and pacing


def status_client(status: int, headers: dict[str, str] | None = None) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, headers=headers or {}, text="<html>body</html>")

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [429, 503])
async def test_rate_limit_carries_retry_after(status: int) -> None:
    async with status_client(status, {"retry-after": "120"}) as client:
        with pytest.raises(SensorRateLimited) as info:
            await FtsSensor(client=client, settings=SETTINGS, sleep=no_sleep).search(query())
    assert info.value.retry_after == 120.0


@pytest.mark.asyncio
async def test_rate_limit_without_retry_after_is_unstated() -> None:
    async with status_client(429) as client:
        with pytest.raises(SensorRateLimited) as info:
            await FtsSensor(client=client, settings=SETTINGS, sleep=no_sleep).search(query())
    assert info.value.retry_after is None


@pytest.mark.asyncio
async def test_other_errors_raise_without_echoing_the_body() -> None:
    async with status_client(400) as client:
        with pytest.raises(SensorError, match="HTTP 400") as info:
            await FtsSensor(client=client, settings=SETTINGS, sleep=no_sleep).search(query())
    assert "body" not in str(info.value)


@pytest.mark.asyncio
async def test_a_non_json_success_is_an_error() -> None:
    async with status_client(200) as client:
        with pytest.raises(SensorError, match="not JSON"):
            await FtsSensor(client=client, settings=SETTINGS, sleep=no_sleep).search(query())


@pytest.mark.asyncio
async def test_calls_are_paced_by_the_minimum_interval() -> None:
    sleeps: list[float] = []

    async def record_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"releases": []})

    sensor = FtsSensor(
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        settings=SETTINGS,
        sleep=record_sleep,
        min_interval_seconds=5.0,
    )
    await sensor.search(query())
    await sensor.search(query())
    assert len(sleeps) == 1 and 0 < sleeps[0] <= 5.0


# ------------------------------------------------------------------------ structured evidence reuse


def structured_for(rel: dict[str, Any], monkeypatch: pytest.MonkeyPatch):
    rules = Settings(_env_file=None, evidence_source_rules={"fts": "structured"})
    monkeypatch.setattr("northvaine.radar.structured.get_settings", lambda: rules)
    doc = parse_release(rel, fetched_at=FETCHED, settings=SETTINGS)
    return doc, structured_evidence(evidence_document_from_sensor(doc))


def test_a_tender_flows_through_structured_evidence(monkeypatch: pytest.MonkeyPatch) -> None:
    doc, out = structured_for(RELEASES["093572-2026"], monkeypatch)
    assert out is not None
    claims, events = out
    lines = doc.text.split("\n")
    assert all(c.source_quote in lines for c in claims)
    assert [e.event_type for e in events] == ["tender_published"]
    assert events[0].occurred_on == date(2026, 10, 2)
    assert events[0].subject is not None and events[0].subject.country == "GB"
    quotes = {c.source_quote for c in claims}
    assert "Deadline: 2026-10-16T12:00:00+01:00" in quotes
    assert "CPV: 80000000" in quotes


def test_an_award_flows_through_structured_evidence(monkeypatch: pytest.MonkeyPatch) -> None:
    doc, out = structured_for(RELEASES["093575-2026"], monkeypatch)
    assert out is not None
    claims, events = out
    lines = doc.text.split("\n")
    assert all(c.source_quote in lines for c in claims)
    assert [e.event_type for e in events] == ["contract_awarded"]
    assert events[0].subject is not None and events[0].subject.name == "Jeakins Weir Ltd."
    assert events[0].subject.country == "GB"
    assert events[0].occurred_on == date(2026, 10, 2)  # no award decision date: publication
    assert events[0].slots["value"] == "64470.68"


def test_every_recorded_release_gives_exact_line_quotes(monkeypatch: pytest.MonkeyPatch) -> None:
    for rel in RELEASES.values():
        if fts.release_kind(rel) is None:
            continue
        doc, out = structured_for(rel, monkeypatch)
        assert out is not None
        lines = doc.text.split("\n")
        for claim in out[0]:
            assert claim.source_quote in lines
            for index_list in [e.claim_indices for e in out[1]]:
                assert all(0 <= i < len(out[0]) for i in index_list)
