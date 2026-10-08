"""USAspending sensor: request building, parsing, rendering, privacy, paging, replay, evidence.
No network: every HTTP exchange is a recorded fixture or a hand-built response."""

from __future__ import annotations

import json
import re
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest

from northvaine.brain.budget import RunContext
from northvaine.core.models import ClaimStatus, EventType
from northvaine.core.settings import Settings
from northvaine.radar.ledger import evidence_document_from_sensor
from northvaine.radar.quote_check import QuoteMode
from northvaine.radar.structured import structured_evidence
from northvaine.radar.verify import verify_claims
from northvaine.sensors.base import Sensor, SensorError, SensorQuery, SensorRateLimited
from northvaine.sensors.replay import load_exchanges
from northvaine.sensors.usaspending import (
    USASPENDING_FIELDS,
    UsaspendingSensor,
    build_request,
    parse_award,
    render_award_text,
)

FIXTURES = Path(__file__).parent.parent / "fixtures" / "sensors" / "usaspending"
SETTINGS = Settings(_env_file=None)
FETCHED = datetime(2026, 10, 9, 9, 0, tzinfo=UTC)
EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
AWARD = [EventType.CONTRACT_AWARDED]
ID_A = "CONT_AWD_ABC123_1443_-NONE-_-NONE-"


async def no_sleep(seconds: float) -> None:
    return None


def recorded_pages() -> list[dict[str, Any]]:
    pages: list[dict[str, Any]] = []
    for path in sorted(FIXTURES.glob("*.json")):
        pages.extend(e.body_json for e in load_exchanges(path))
    return pages


PAGES = recorded_pages()
RECORDS = [r for p in PAGES for r in p["results"]]


def award(**kw: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "Award ID": "ABC123",
        "Recipient Name": "EXAMPLE BUILDERS LLC",
        "Award Amount": 125000.5,
        "Awarding Agency": "Department of Examples",
        "Awarding Sub Agency": "Bureau of Samples",
        "Description": "REPAIR OF ROAD 12",
        "Start Date": "2026-09-01",
        "End Date": "2027-09-01",
        "Base Obligation Date": "2026-09-01",
        "Last Modified Date": "2026-09-03 10:00:00",
        "NAICS": {"code": "237310", "description": "HIGHWAY"},
        "PSC": {"code": "Y1LB", "description": "CONSTRUCTION"},
        "Contract Award Type": "DEFINITIVE CONTRACT",
        "Place of Performance Country Code": "USA",
        "Place of Performance State Code": "AZ",
        "generated_internal_id": ID_A,
    }
    base.update(kw)
    return base


def numbered(i: int, **kw: Any) -> dict[str, Any]:
    return award(
        **{"Award ID": str(i), "generated_internal_id": f"CONT_AWD_{i}_1_-NONE-_-NONE-", **kw}
    )


def query(**kw: Any) -> SensorQuery:
    base: dict[str, Any] = {
        "kinds": AWARD,
        "countries": ["US"],
        "published_from": date(2026, 9, 1),
        "published_to": date(2026, 9, 30),
        "max_results": 50,
    }
    base.update(kw)
    return SensorQuery(**base)


def page(records: list[dict[str, Any]], has_next: bool = False) -> dict[str, Any]:
    return {"results": records, "page_metadata": {"page": 1, "hasNext": has_next}}


def client_for(pages: list[dict[str, Any]], bodies: list[dict[str, Any]]) -> httpx.AsyncClient:
    """Serves `pages` in order and keeps each request body in `bodies`."""
    queue = list(pages)

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json=queue.pop(0))

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def sensor(http: httpx.AsyncClient, settings: Settings = SETTINGS) -> UsaspendingSensor:
    return UsaspendingSensor(client=http, settings=settings, sleep=no_sleep)


def parsed(record: dict[str, Any], settings: Settings = SETTINGS):
    return parse_award(record, fetched_at=FETCHED, settings=settings)


# ------------------------------------------------------------------------ request building


def test_request_body_shape() -> None:
    body = build_request(query(codes=["naics:237310", "psc:y1lb"], text=" bridge  deck "))
    assert body["filters"]["award_type_codes"] == ["A", "B", "C", "D"]
    assert body["filters"]["time_period"] == [
        {"start_date": "2026-09-01", "end_date": "2026-09-30", "date_type": "new_awards_only"}
    ]
    assert body["filters"]["naics_codes"] == ["237310"]
    assert body["filters"]["psc_codes"] == ["Y1LB"]
    assert body["filters"]["keywords"] == ["bridge deck"]
    assert body["fields"] == list(USASPENDING_FIELDS)
    assert (body["limit"], body["page"], body["sort"]) == (50, 1, "Base Obligation Date")


def test_requested_fields_never_include_addresses_or_contacts() -> None:
    for field in USASPENDING_FIELDS:
        assert not re.search(r"location|address|email|phone|duns|uei|contact", field, re.I)


def test_limit_is_capped_at_the_api_maximum() -> None:
    assert build_request(query(max_results=250))["limit"] == 100


def test_as_of_caps_the_window_end_by_the_lag() -> None:
    as_of = datetime(2026, 9, 10, 12, 0, tzinfo=UTC)
    body = build_request(query(), as_of=as_of, settings=SETTINGS)
    # lag 3 days: nothing modified on or after 7 Sep is requested
    assert body["filters"]["time_period"][0]["end_date"] == "2026-09-07"


def test_without_a_start_the_window_is_the_default_length() -> None:
    body = build_request(query(published_from=None), settings=SETTINGS)
    period = body["filters"]["time_period"][0]
    start, end = date.fromisoformat(period["start_date"]), date.fromisoformat(period["end_date"])
    assert (end - start).days == SETTINGS.usaspending_default_window_days


def test_ignored_schemes_add_no_filter() -> None:
    body = build_request(query(codes=["cpv:45000000", "naics:12x"]))
    assert "naics_codes" not in body["filters"] and "psc_codes" not in body["filters"]


def test_award_kind_is_required_and_as_of_must_be_aware() -> None:
    with pytest.raises(ValueError, match="contract awards only"):
        build_request(query(kinds=[EventType.TENDER_PUBLISHED]))
    with pytest.raises(ValueError, match="timezone-aware"):
        build_request(query(), as_of=datetime(2026, 9, 10))


# ------------------------------------------------------------------------ parsing and rendering


def test_rendered_lines_follow_the_structured_format() -> None:
    text = render_award_text(award(), settings=SETTINGS)
    assert text.split("\n") == [
        "Notice: ABC123 (DEFINITIVE CONTRACT)",
        f"Procedure: {ID_A}",
        "Published: 2026-09-03",
        "Title [eng]: REPAIR OF ROAD 12",
        "Buyer [eng]: Bureau of Samples; Department of Examples",
        "Buyer country: US",
        "Winner [eng]: EXAMPLE BUILDERS LLC",
        "NAICS: 237310",
        "PSC: Y1LB",
        "Winner decision date: 2026-09-01",
        "Contract start: 2026-09-01",
        "Contract end: 2027-09-01",
        "Place of performance: AZ, USA",
        "Total value: 125000.50 USD",
    ]


def test_rendering_is_deterministic_and_skips_absent_fields() -> None:
    sparse = {"generated_internal_id": "CONT_AWD_X_1_-NONE-_-NONE-"}
    assert render_award_text(sparse, settings=SETTINGS) == "Procedure: CONT_AWD_X_1_-NONE-_-NONE-"
    assert render_award_text(award(), settings=SETTINGS) == render_award_text(
        award(), settings=SETTINGS
    )


def test_meta_and_document_fields() -> None:
    doc = parsed(award())
    assert doc.source == "usaspending"
    assert doc.url == f"https://www.usaspending.gov/award/{ID_A}"
    assert doc.external_id == doc.group_key == ID_A
    assert doc.published_on == date(2026, 9, 3)
    assert doc.available_at == datetime(2026, 9, 6, tzinfo=UTC)  # + 3 days lag
    assert doc.date_flags == []
    meta = doc.meta
    assert meta["schema_ver"] == 1 and meta["notice_kind"] == "contract_awarded"
    assert meta["buyers"] == ["Bureau of Samples", "Department of Examples"]
    assert meta["buyer_countries"] == ["US"]
    assert meta["winners"] == [{"name": "EXAMPLE BUILDERS LLC", "country": None}]
    assert meta["naics_codes"] == ["237310"] and meta["psc_codes"] == ["Y1LB"]
    assert meta["value"] == pytest.approx(125000.5) and meta["currency"] == "USD"
    assert meta["raw_dates"]["winner_decisions"] == ["2026-09-01"]


def test_award_without_a_usable_id_is_refused() -> None:
    for bad in (None, "", "has space/slash"):
        with pytest.raises(ValueError):
            parsed(award(generated_internal_id=bad))


def test_missing_dates_are_flagged_not_invented() -> None:
    doc = parsed(award(**{"Last Modified Date": None, "Base Obligation Date": None}))
    assert doc.published_on is None and doc.available_at is None
    assert [f.value for f in doc.date_flags] == ["missing_publication"]


def test_zero_value_is_not_stated_and_long_titles_are_cut() -> None:
    doc = parsed(award(**{"Award Amount": 0, "Description": "X" * 500}))
    assert "Total value" not in doc.text and doc.meta["value"] is None
    assert len(doc.title or "") == SETTINGS.usaspending_title_max_chars + 3


# ------------------------------------------------------------------------ privacy


@pytest.mark.parametrize(
    "name",
    [
        "REDACTED DUE TO PII",
        "JANE Q DOE d/b/a Doe Fencing",
        "Doe Fencing, Sole Proprietorship",
        "SMITH, JOHN",
        "SMITH, JOHN A",
        "JOHN Q SMITH",
        "Maria T. Garcia",
        "Hans Mueller Inhaber",  # marker shared with TED (D76)
    ],
)
def test_natural_persons_are_withheld(name: str) -> None:
    doc = parsed(award(**{"Recipient Name": name}))
    assert doc.meta["winners"][0]["name"].startswith("[")
    for word in name.split():
        if len(word) > 4:
            assert word not in doc.text
    # the placeholder is stable
    assert parsed(award(**{"Recipient Name": name})).meta["winners"] == doc.meta["winners"]


@pytest.mark.parametrize(
    "name",
    [
        "EXAMPLE BUILDERS LLC",
        "SMITH & SONS CONSTRUCTION, INC.",
        "SMITH, JONES AND ASSOCIATES, LLP",
        "Acme Corp",
        "CUTTING EDGE CONTRACTORS INC",
        "Stone Ridge Construction",
    ],
)
def test_companies_are_kept(name: str) -> None:
    assert parsed(award(**{"Recipient Name": name})).meta["winners"][0]["name"] == name


def test_person_shaped_check_can_be_switched_off() -> None:
    cfg = Settings(_env_file=None, usaspending_withhold_person_shaped_names=False)
    doc = parsed(award(**{"Recipient Name": "JOHN Q SMITH"}), cfg)
    assert doc.meta["winners"][0]["name"] == "JOHN Q SMITH"


def test_markers_are_data_in_settings() -> None:
    cfg = Settings(_env_file=None, usaspending_natural_person_markers=("ZZMARK",))
    assert (
        parsed(award(**{"Recipient Name": "Acme ZZMARK"}), cfg)
        .meta["winners"][0]["name"]
        .startswith("[")
    )


def test_unnamed_recipients_give_no_winner() -> None:
    doc = parsed(award(**{"Recipient Name": "MULTIPLE RECIPIENTS"}))
    assert doc.meta["winners"] == [] and "Winner [" not in doc.text


def test_contact_details_in_free_text_are_scrubbed() -> None:
    doc = parsed(award(Description="CALL +1 555 123 4567 OR MAIL a.b@agency.gov"))
    assert "@" not in doc.text and "4567" not in doc.text
    assert "[email removed]" in doc.text and "[phone removed]" in doc.text


def test_unrequested_fields_are_never_read() -> None:
    doc = parsed(
        award(
            **{
                "Recipient Location": {"address_line1": "1 SECRET STREET", "city_name": "X"},
                "Recipient UEI": "UEI123SECRET",
                "Primary Place of Performance": {"address_line1": "2 HIDDEN ROAD"},
            }
        )
    )
    blob = doc.text + json.dumps(doc.meta, default=str)
    for secret in ("SECRET", "HIDDEN"):
        assert secret not in blob


def test_recorded_fixtures_hold_no_email_or_phone_or_address() -> None:
    for path in FIXTURES.glob("*.json"):
        raw = path.read_text(encoding="utf-8")
        assert not EMAIL.search(raw)
        assert "Recipient Location" not in raw and "address" not in raw.lower()


# ------------------------------------------------------------------------ recorded replay


def test_every_recorded_award_parses_with_exact_line_content() -> None:
    assert len(RECORDS) == 12
    for record in RECORDS:
        doc = parsed(record)
        assert doc.url.startswith("https://www.usaspending.gov/award/CONT_AWD_")
        assert doc.text == render_award_text(record, settings=SETTINGS)
        assert doc.meta["winners"] and doc.meta["value"]
        assert doc.published_on is not None and doc.date_flags == []
        assert EMAIL.search(doc.text) is None


@pytest.mark.asyncio
async def test_search_replays_recorded_pages() -> None:
    bodies: list[dict[str, Any]] = []
    result = await sensor(client_for(PAGES, bodies)).search(
        query(codes=["naics:237310"], max_results=12)
    )
    assert len(result.documents) == 12
    assert result.enumerable is True and result.truncated is True
    assert result.next_cursor == "3"  # page 2 had more behind it
    assert {d.source for d in result.documents} == {"usaspending"}
    assert [b["page"] for b in bodies] == [1, 2]
    assert bodies[0]["filters"]["naics_codes"] == ["237310"]


# ------------------------------------------------------------------------ sensor behaviour


def test_sensor_protocol_and_flags() -> None:
    s = UsaspendingSensor(settings=SETTINGS)
    assert isinstance(s, Sensor)
    assert (s.name, s.enumerable, s.tier.value) == ("usaspending", True, "official")


@pytest.mark.asyncio
async def test_non_us_query_and_unusable_codes_fetch_nothing() -> None:
    bodies: list[dict[str, Any]] = []
    s = sensor(client_for([], bodies))
    gb = await s.search(query(countries=["GB"]))
    cpv_only = await s.search(query(codes=["cpv:45000000"]))
    assert gb.documents == [] and cpv_only.documents == [] and bodies == []
    assert gb.notes and cpv_only.notes


@pytest.mark.asyncio
async def test_duplicates_and_unusable_awards_are_dropped_with_notes() -> None:
    a, b, bad = award(), numbered(7), award(generated_internal_id=None)
    result = await sensor(client_for([page([a, a, b, bad])], [])).search(query())
    assert [d.external_id for d in result.documents] == [ID_A, "CONT_AWD_7_1_-NONE-_-NONE-"]
    assert any("skipped 1" in n for n in result.notes)
    assert result.truncated is False and result.next_cursor is None


@pytest.mark.asyncio
async def test_max_results_cut_and_cursor_continue() -> None:
    records = [numbered(i) for i in range(3)]
    bodies: list[dict[str, Any]] = []
    first = await sensor(client_for([page(records, has_next=True)], bodies)).search(
        query(max_results=2)
    )
    assert len(first.documents) == 2 and first.truncated and first.next_cursor is None
    second = await sensor(client_for([page(records[:1])], bodies)).search(query(), cursor="4")
    assert bodies[-1]["page"] == 4 and len(second.documents) == 1
    with pytest.raises(ValueError, match="page number"):
        await sensor(client_for([], [])).search(query(), cursor="abc")


@pytest.mark.asyncio
async def test_page_cap_sets_truncated_and_a_cursor() -> None:
    cfg = Settings(_env_file=None, usaspending_max_pages=2)
    pages = [page([numbered(i)], has_next=True) for i in range(2)]
    result = await sensor(client_for(pages, []), cfg).search(query())
    assert result.truncated is True and result.next_cursor == "3"


@pytest.mark.asyncio
async def test_as_of_drops_records_modified_after_it() -> None:
    late = numbered(9, **{"Last Modified Date": "2026-09-30"})
    result = await sensor(client_for([page([award(), late])], [])).search(
        query(), as_of=datetime(2026, 9, 20, tzinfo=UTC)
    )
    assert [d.external_id for d in result.documents] == [ID_A]
    assert any("after as_of" in n for n in result.notes)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "error"),
    [(429, SensorRateLimited), (503, SensorRateLimited), (500, SensorError)],
)
async def test_http_errors_never_echo_the_body(status: int, error: type[Exception]) -> None:
    http = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(status, text="LEAK-ME"))
    )
    with pytest.raises(error) as info:
        await sensor(http).search(query())
    assert "LEAK-ME" not in str(info.value)


@pytest.mark.asyncio
async def test_non_json_and_wrong_shape_are_errors() -> None:
    for response in (httpx.Response(200, text="<html>"), httpx.Response(200, json=[1])):
        http = httpx.AsyncClient(transport=httpx.MockTransport(lambda r, x=response: x))
        with pytest.raises(SensorError):
            await sensor(http).search(query())


# ------------------------------------------------------------------------ structured evidence


@pytest.fixture(autouse=True)
def _structured_rules(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("northvaine.radar.structured.get_settings", lambda: SETTINGS)


def test_an_award_flows_through_structured_evidence() -> None:
    doc = parsed(award())
    out = structured_evidence(evidence_document_from_sensor(doc))
    assert out is not None
    claims, events = out
    lines = doc.text.split("\n")
    assert all(c.source_quote in lines for c in claims)
    quotes = {c.source_quote for c in claims}
    assert {"NAICS: 237310", "PSC: Y1LB", "Total value: 125000.50 USD"} <= quotes
    assert "Winner [eng]: EXAMPLE BUILDERS LLC" in quotes
    assert [e.event_type for e in events] == ["contract_awarded"]
    event = events[0]
    assert event.subject is not None and event.subject.name == "EXAMPLE BUILDERS LLC"
    assert event.occurred_on == date(2026, 9, 1)  # the base obligation date
    assert event.slots["naics_codes"] == "237310" and event.slots["psc_codes"] == "Y1LB"
    assert event.slots["buyer_countries"] == "US" and event.slots["value"] == "125000.50"
    assert event.slots["buyer_names"] == "Bureau of Samples; Department of Examples"


def test_a_withheld_person_is_a_placeholder_in_evidence() -> None:
    doc = parsed(award(**{"Recipient Name": "SMITH, JOHN"}))
    out = structured_evidence(evidence_document_from_sensor(doc))
    assert out is not None
    assert all("SMITH" not in c.source_quote for c in out[0])
    assert out[1][0].subject is not None and out[1][0].subject.name.startswith("[")


@pytest.mark.asyncio
async def test_recorded_awards_give_verified_structured_claims() -> None:
    for record in RECORDS:
        doc = evidence_document_from_sensor(parsed(record))
        out = structured_evidence(doc)
        assert out is not None
        claims, events = out
        assert claims and len(events) == 1
        checks = await verify_claims(
            doc,
            claims,
            run=RunContext(),
            mode=QuoteMode.STRUCTURED,
            support=False,
            settings=SETTINGS,
        )
        assert all(c.status == ClaimStatus.VERIFIED for c in checks)
        assert all(0 <= i < len(claims) for i in events[0].claim_indices)
