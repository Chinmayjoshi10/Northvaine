"""World Bank procurement notices sensor: request mapping, parsing, rendering, availability,
privacy, paging, replay. No network: every HTTP exchange is a recorded fixture or a
hand-built response. Fixtures: tests/fixtures/sensors/worldbank/ (page size 6)."""

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
from northvaine.sensors import worldbank
from northvaine.sensors.base import (
    DateFlag,
    Sensor,
    SensorError,
    SensorQuery,
    SensorRateLimited,
)
from northvaine.sensors.registry import SENSOR_NAMES, get_sensor
from northvaine.sensors.replay import load_exchanges, replay_transport
from northvaine.sensors.ted import NATURAL_PERSON_PREFIX
from northvaine.sensors.worldbank import (
    WorldBankSensor,
    build_request,
    country_iso2,
    parse_award_text,
    parse_notice,
    render_notice_text,
)

FIXTURES = Path(__file__).parent.parent / "fixtures" / "sensors" / "worldbank"
SETTINGS = Settings(_env_file=None, worldbank_page_size=6)
FETCHED = datetime(2026, 10, 9, 9, 0, tzinfo=UTC)
EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
TENDER = [EventType.TENDER_PUBLISHED]
AWARD = [EventType.CONTRACT_AWARDED]
DAY = date(2026, 10, 7)


async def no_sleep(seconds: float) -> None:
    return None


def recorded_notices() -> dict[str, dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}
    for path in sorted(FIXTURES.glob("*.json")):
        for exchange in json.loads(path.read_text(encoding="utf-8")):
            for notice in exchange["body_json"]["procnotices"]:
                if "notice_type" in notice:  # one-row bisection probes carry only id and date
                    found[notice["id"]] = notice
    return found


NOTICES = recorded_notices()


def award_html(
    winners: str = "<b>ACME SUPPLY LTD (123)</b><br/>Country: India<br/>",
    prices: str = "Signed Contract price<br/>USD 1000.50",
    decision: str = "2026/09/01",
) -> str:
    return (
        "<div class='row col-sm-12'><h4>Contract Award</h4></div>"
        f"<div class='row'><div class='col-sm-4'><b>Date Notification of Award Issued</b><br/>"
        f"(YYYY/MM/DD)<br/>{decision}<br/></div></div>"
        f"<div class='row'><div class='col-sm-12'><u><b>Awarded Bidder(s):</b></u></div>"
        f"<div class='row col-sm-12'>{winners}"
        f"<div class='col-sm-7'>{prices}</div><br/></div></div>"
        "<div class='row'><div class='col-sm-12'><u><b>Rejected Bidder(s):</b></u></div>"
        "<b>LOSER LTD (999)</b><br/>Country: France<br/></div>"
    )


def notice(**kw: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": "OP00000001",
        "notice_type": "Invitation for Bids",
        "noticedate": "07-Oct-2026",
        "notice_lang_name": "English",
        "submission_deadline_date": "2026-11-20T00:00:00Z",
        "project_ctry_name": "Kenya",
        "project_id": "P000001",
        "project_name": "Example Project",
        "bid_reference_no": "KE-REF-1",
        "bid_description": "Supply of example goods",
        "procurement_group": "GO",
        "procurement_method_code": "RFB",
        "procurement_method_name": "Request for Bids",
        "contact_organization": "Example Authority",
        "contact_ctry_name": "Kenya",
    }
    base.update(kw)
    return base


def award(**kw: Any) -> dict[str, Any]:
    base = notice(notice_type="Contract Award", notice_text=award_html())
    base.pop("submission_deadline_date")
    base.pop("contact_organization")
    base.pop("contact_ctry_name")
    base.update(kw)
    return base


# ----------------------------------------------------------------------------- registry


def test_registered_and_conforms_to_the_sensor_protocol() -> None:
    assert "worldbank" in SENSOR_NAMES
    sensor = get_sensor("worldbank")
    assert isinstance(sensor, WorldBankSensor)
    assert isinstance(sensor, Sensor)
    assert sensor.name == "worldbank"
    assert sensor.tier.value == "official"
    assert sensor.enumerable is True


def test_settings_register_the_source() -> None:
    s = Settings(_env_file=None)
    assert s.evidence_source_rules["worldbank"] == "structured"
    assert "worldbank" in s.radar_enumerable_sources


# ----------------------------------------------------------------------------- query building


def test_build_request_for_a_tender_type_asks_no_contact_field_and_no_free_text() -> None:
    q = SensorQuery(kinds=TENDER)
    params = build_request(q, "Invitation for Bids", offset=12, settings=SETTINGS)
    assert list(params) == ["format", "rows", "os", "fl", "notice_type"]
    assert params["format"] == "json"
    assert params["rows"] == "6"
    assert params["os"] == "12"
    assert params["notice_type"] == "Invitation for Bids"
    assert "contact_" not in params["fl"].replace("contact_organization", "").replace(
        "contact_ctry_name", ""
    )
    assert "notice_text" not in params["fl"]


def test_build_request_reads_the_award_text_only_for_awards() -> None:
    q = SensorQuery(kinds=AWARD)
    assert "notice_text" in build_request(q, "Contract Award", settings=SETTINGS)["fl"]


def test_build_request_maps_text_to_qterm() -> None:
    q = SensorQuery(kinds=TENDER, text="example term")
    params = build_request(q, "Invitation for Bids", settings=SETTINGS)
    assert params["qterm"] == "example term"
    assert list(params)[-1] == "qterm"


def test_build_request_rejects_an_unknown_notice_type() -> None:
    with pytest.raises(ValueError, match="not in worldbank_notice_types"):
        build_request(SensorQuery(kinds=TENDER), "Bogus", settings=SETTINGS)


def test_kinds_choose_the_notice_types_in_settings_order() -> None:
    both = SensorQuery(kinds=[*AWARD, *TENDER])
    assert worldbank.notice_types_for(both, SETTINGS) == [
        "Invitation for Bids",
        "Request for Expression of Interest",
        "Contract Award",
    ]
    assert worldbank.notice_types_for(SensorQuery(kinds=AWARD), SETTINGS) == ["Contract Award"]
    other = SensorQuery(kinds=[EventType.FACILITY_OPENED])
    assert worldbank.notice_types_for(other, SETTINGS) == []


def test_notice_types_are_data() -> None:
    custom = Settings(
        _env_file=None, worldbank_notice_types={"General Procurement Notice": "market_entry"}
    )
    q = SensorQuery(kinds=[EventType.MARKET_ENTRY])
    assert worldbank.notice_types_for(q, custom) == ["General Procurement Notice"]


def test_window_upper_applies_the_availability_lag() -> None:
    q = SensorQuery(kinds=TENDER, published_to=date(2026, 10, 9))
    as_of = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)
    assert worldbank.window_upper(q, as_of, SETTINGS) == date(2026, 10, 4)
    assert worldbank.window_upper(q, None, SETTINGS) == date(2026, 10, 9)
    with pytest.raises(ValueError, match="timezone-aware"):
        worldbank.window_upper(q, datetime(2026, 10, 5), SETTINGS)


# ----------------------------------------------------------------------------- text helpers


def test_repair_undoes_double_encoded_utf8_and_leaves_good_text() -> None:
    assert worldbank._repair("AquisiÃ§Ã£o") == "Aquisição"
    assert worldbank._repair("Manual â€“ 2000") == "Manual – 2000"  # noqa: RUF001
    assert worldbank._repair("Aquisição") == "Aquisição"
    assert worldbank._repair("plain ascii") == "plain ascii"
    assert worldbank._repair("日本語") == "日本語"


def test_iso_dates_from_the_three_source_formats() -> None:
    assert worldbank._iso_date("07-Oct-2026") == "2026-10-07"
    assert worldbank._iso_date("2026/08/20") == "2026-08-20"
    assert worldbank._iso_date("2026-10-23T00:00:00Z") == "2026-10-23"
    assert worldbank._iso_date("31-Feb-2026") is None
    assert worldbank._iso_date("soon") is None
    assert worldbank._iso_date(None) is None


def test_country_names_resolve_through_iso_names_and_aliases_not_regions() -> None:
    assert country_iso2("Kenya", SETTINGS) == "KE"
    assert country_iso2("Türkiye", SETTINGS) == "TR"
    assert country_iso2("Congo, Democratic Republic of", SETTINGS) == "CD"
    assert country_iso2("Lao People's Democratic Republic", SETTINGS) == "LA"
    assert country_iso2("Eastern and Southern Africa", SETTINGS) is None
    assert country_iso2("", SETTINGS) is None
    assert country_iso2(None, SETTINGS) is None


def test_amounts() -> None:
    assert worldbank._amount("1302445953.00") == 1302445953.0
    assert worldbank._amount("1,000,000.50") == 1000000.5
    assert worldbank._amount("0.00") is None
    assert worldbank._amount("1,00") is None
    assert worldbank._amount("1.2.3") is None


# ----------------------------------------------------------------------------- award text


def test_award_text_reads_only_the_awarded_section() -> None:
    result = parse_award_text(award_html())
    assert result["winners"] == [{"name": "ACME SUPPLY LTD", "country_name": "India"}]
    assert result["prices"] == [(1000.5, "USD")]
    assert result["decision"] == "2026-09-01"


def test_award_text_with_a_joint_venture_and_one_price() -> None:
    winners = "<b>ONE CO (1)</b><br/>Country: Kenya<br/><b>TWO CO (2)</b><br/>Country: Uganda<br/>"
    result = parse_award_text(award_html(winners=winners))
    assert [w["name"] for w in result["winners"]] == ["ONE CO", "TWO CO"]
    assert len(result["prices"]) == 1


def test_award_text_skips_addresses_and_beneficial_owner_blocks() -> None:
    winners = (
        "<b>ACME LTD (5)</b><br/>1 Example Street, Town Tel: 0000000000 Email: x@example.org<br/>"
        "Country: Kenya<br/>"
        "<div class='col-sm-12'><b>Beneficial Ownership Details</b></div>"
        "<b>ACME LTD (5)</b><br/>Form Date: 28-SEP-26<br/>"
        "<table><tbody><tr><td>Some Person</td></tr></tbody></table>"
    )
    result = parse_award_text(award_html(winners=winners))
    assert result["winners"] == [{"name": "ACME LTD", "country_name": "Kenya"}]
    assert "Some Person" not in json.dumps(result)
    assert "example.org" not in json.dumps(result)


def test_award_text_without_a_section_gives_nothing() -> None:
    assert parse_award_text("<p>nothing</p>")["winners"] == []
    assert parse_award_text("")["prices"] == []


# ----------------------------------------------------------------------------- rendering


def test_tender_lines_follow_the_ted_and_fts_format() -> None:
    doc = parse_notice(notice(), fetched_at=FETCHED, settings=SETTINGS)
    assert doc.text.split("\n") == [
        "Notice: OP00000001 (Invitation for Bids)",
        "Procedure: KE-REF-1",
        "Published: 2026-10-07",
        "Title [eng]: Supply of example goods",
        "Buyer [eng]: Example Authority",
        "Buyer country: KE",
        "Project: P000001 - Example Project",
        "Project country: Kenya",
        "Procurement method: Request for Bids (RFB)",
        "Procurement group: GO",
        "Deadline: 2026-11-20",
    ]
    assert doc.source == "worldbank"
    assert doc.tier.value == "official"
    assert doc.url == (
        "https://projects.worldbank.org/en/projects-operations/procurement-detail/OP00000001"
    )
    assert doc.external_id == "OP00000001"
    assert doc.group_key == "P000001/KE-REF-1"
    assert doc.language == "en"
    assert doc.published_on == DAY


def test_award_lines_carry_winner_value_and_decision_date() -> None:
    doc = parse_notice(award(), fetched_at=FETCHED, settings=SETTINGS)
    lines = doc.text.split("\n")
    assert "Winner [eng]: ACME SUPPLY LTD" in lines
    assert "Winner country: IN" in lines
    assert "Winner decision date: 2026-09-01" in lines
    assert "Total value: 1000.50 USD" in lines
    assert not any(line.startswith("Buyer") for line in lines)  # an award names no buyer field
    assert "LOSER" not in doc.text
    assert doc.meta["winners"] == [{"name": "ACME SUPPLY LTD", "country": "IN"}]
    assert doc.meta["value"] == 1000.5
    assert doc.meta["currency"] == "USD"
    assert doc.meta["winner_decision_dates"] == ["2026-09-01"]


def test_rendering_is_deterministic_and_matches_the_document() -> None:
    n = award()
    assert render_notice_text(n, settings=SETTINGS) == render_notice_text(n, settings=SETTINGS)
    assert (
        render_notice_text(n, settings=SETTINGS)
        == parse_notice(n, fetched_at=FETCHED, settings=SETTINGS).text
    )


def test_several_prices_state_no_total() -> None:
    prices = "Signed Contract price<br/>USD 10.00<br/>Signed Contract price<br/>USD 20.00"
    doc = parse_notice(
        award(notice_text=award_html(prices=prices)), fetched_at=FETCHED, settings=SETTINGS
    )
    assert "Total value" not in doc.text
    assert doc.meta["value"] is None
    assert "multiple_contract_values_total_not_stated" in doc.meta["notes"]


def test_an_award_with_no_readable_winner_says_so() -> None:
    doc = parse_notice(award(notice_text="<p>x</p>"), fetched_at=FETCHED, settings=SETTINGS)
    assert doc.meta["winners"] == []
    assert "winner_not_found_in_notice_text" in doc.meta["notes"]


def test_mojibake_in_text_fields_is_repaired() -> None:
    doc = parse_notice(
        notice(bid_description="AquisiÃ§Ã£o de Viaturas", notice_lang_name="Portuguese"),
        fetched_at=FETCHED,
        settings=SETTINGS,
    )
    assert "Title [por]: Aquisição de Viaturas" in doc.text.split("\n")


def test_unknown_language_is_labelled_und_and_has_no_language_code() -> None:
    doc = parse_notice(notice(notice_lang_name="Klingon"), fetched_at=FETCHED, settings=SETTINGS)
    assert any(line.startswith("Title [und]") for line in doc.text.split("\n"))
    assert doc.language is None


def test_a_region_gives_no_buyer_country() -> None:
    doc = parse_notice(
        notice(project_ctry_name="Eastern and Southern Africa", contact_ctry_name=None),
        fetched_at=FETCHED,
        settings=SETTINGS,
    )
    assert "Buyer country" not in doc.text
    assert doc.meta["buyer_countries"] == []


def test_notice_without_an_id_raises() -> None:
    with pytest.raises(ValueError, match="no id"):
        parse_notice(notice(id=None), fetched_at=FETCHED, settings=SETTINGS)


# ----------------------------------------------------------------------------- availability


def test_available_at_comes_from_the_notice_date_with_the_lag() -> None:
    doc = parse_notice(notice(), fetched_at=FETCHED, settings=SETTINGS)
    assert doc.available_at == datetime(2026, 10, 8, tzinfo=UTC)
    assert doc.date_flags == []


def test_award_date_never_sets_availability_and_an_old_award_is_flagged() -> None:
    doc = parse_notice(
        award(notice_text=award_html(decision="2022/02/22")), fetched_at=FETCHED, settings=SETTINGS
    )
    assert doc.available_at == datetime(2026, 10, 8, tzinfo=UTC)
    assert DateFlag.EXTREME_LAG in doc.date_flags


def test_an_unreadable_notice_date_is_flagged_not_guessed() -> None:
    doc = parse_notice(notice(noticedate="someday"), fetched_at=FETCHED, settings=SETTINGS)
    assert doc.available_at is None
    assert doc.published_on is None
    assert DateFlag.UNPARSEABLE in doc.date_flags
    assert DateFlag.MISSING_PUBLICATION in doc.date_flags


def test_a_deadline_before_publication_is_flagged() -> None:
    doc = parse_notice(
        notice(submission_deadline_date="2026-10-01T00:00:00Z"),
        fetched_at=FETCHED,
        settings=SETTINGS,
    )
    assert DateFlag.DEADLINE_BEFORE_PUBLICATION in doc.date_flags


# ----------------------------------------------------------------------------- privacy


def test_individual_method_notices_are_skipped_by_the_sensor_rule() -> None:
    assert worldbank.is_skipped(notice(procurement_method_code="INDV"), SETTINGS)
    assert not worldbank.is_skipped(notice(), SETTINGS)
    assert not worldbank.is_skipped(notice(procurement_method_code=None), SETTINGS)


def test_direct_selection_winners_are_withheld_whatever_the_name() -> None:
    doc = parse_notice(award(procurement_method_code="CDS"), fetched_at=FETCHED, settings=SETTINGS)
    name = doc.meta["winners"][0]["name"]
    assert name.startswith(NATURAL_PERSON_PREFIX)
    assert "ACME" not in doc.text
    again = parse_notice(
        award(procurement_method_code="CDS"), fetched_at=FETCHED, settings=SETTINGS
    )
    assert again.meta["winners"][0]["name"] == name  # stable


def test_personal_markers_withhold_a_winner_and_a_buyer() -> None:
    winners = (
        "<b>Mr. Example Person (7)</b><br/>Country: Kenya<br/>"
        "<b>REAL CO LTD (8)</b><br/>Country: Kenya<br/>"
    )
    doc = parse_notice(
        award(notice_text=award_html(winners=winners)), fetched_at=FETCHED, settings=SETTINGS
    )
    names = [w["name"] for w in doc.meta["winners"]]
    assert names[0].startswith(NATURAL_PERSON_PREFIX)
    assert names[1] == "REAL CO LTD"
    assert "Example Person" not in doc.text
    buyer = parse_notice(
        notice(contact_organization="Ms. Example Person"), fetched_at=FETCHED, settings=SETTINGS
    )
    assert buyer.meta["buyers"][0].startswith(NATURAL_PERSON_PREFIX)
    assert "Example Person" not in buyer.text


def test_the_ted_markers_still_apply() -> None:
    winners = "<b>Max Muster e.K. (7)</b><br/>Country: Germany<br/>"
    doc = parse_notice(
        award(notice_text=award_html(winners=winners)), fetched_at=FETCHED, settings=SETTINGS
    )
    assert doc.meta["winners"][0]["name"].startswith(NATURAL_PERSON_PREFIX)


def test_markers_are_data_not_code() -> None:
    custom = Settings(_env_file=None, worldbank_natural_person_markers=("ACME",))
    doc = parse_notice(award(), fetched_at=FETCHED, settings=custom)
    assert doc.meta["winners"][0]["name"].startswith(NATURAL_PERSON_PREFIX)


def test_emails_in_text_fields_are_removed() -> None:
    doc = parse_notice(
        notice(bid_description="Supply to buyer@example.org now"),
        fetched_at=FETCHED,
        settings=SETTINGS,
    )
    assert "buyer@example.org" not in doc.text
    assert "[email removed]" in doc.text


def test_contact_fields_never_reach_the_document() -> None:
    doc = parse_notice(
        notice(
            contact_email="person@example.org",
            contact_phone_no="+10000000000",
            contact_name="Some Person",
            contact_address="1 Example Street",
        ),
        fetched_at=FETCHED,
        settings=SETTINGS,
    )
    blob = doc.text + json.dumps(doc.meta)
    for secret in ("person@example.org", "+10000000000", "Some Person", "Example Street"):
        assert secret not in blob


def test_no_recorded_document_holds_an_email_phone_or_address() -> None:
    assert NOTICES
    for n in NOTICES.values():
        if worldbank.is_skipped(n, SETTINGS) or worldbank.notice_kind(n, SETTINGS) is None:
            continue
        doc = parse_notice(n, fetched_at=FETCHED, settings=SETTINGS)
        blob = doc.text + json.dumps(doc.meta)
        assert not EMAIL.search(blob)
        assert not re.search(r"(?i)(tel|phone|e-?mail)", blob)
        assert "Beneficial" not in blob


# ----------------------------------------------------------------------------- recorded notices


def test_every_recorded_notice_parses_with_exact_line_structure() -> None:
    kinds = set()
    for n in NOTICES.values():
        doc = parse_notice(n, fetched_at=FETCHED, settings=SETTINGS)
        kinds.add(doc.meta["notice_kind"])
        lines = doc.text.split("\n")
        assert lines[0].startswith("Notice: ")
        assert any(line.startswith("Published: ") for line in lines)
        assert doc.available_at is not None
        assert doc.meta["schema_ver"] == 1
    assert kinds == {"tender_published", "contract_awarded"}


def test_recorded_awards_carry_a_winner_and_a_value() -> None:
    awards = [n for n in NOTICES.values() if n["notice_type"] == "Contract Award"]
    assert len(awards) >= 10
    with_winner = with_value = 0
    for n in awards:
        doc = parse_notice(n, fetched_at=FETCHED, settings=SETTINGS)
        with_winner += bool(doc.meta["winners"])
        with_value += bool(doc.meta["value"])
    assert with_winner == len(awards)
    assert with_value >= len(awards) - 2  # a few awards list several prices


def test_recorded_individuals_are_withheld() -> None:
    texts = [
        parse_notice(n, fetched_at=FETCHED, settings=SETTINGS).text
        for n in NOTICES.values()
        if n.get("procurement_method_code") == "CDS"
    ]
    assert texts
    assert all(NATURAL_PERSON_PREFIX in t or "natural person redacted" in t for t in texts)


# ----------------------------------------------------------------------------- structured evidence


def structured_for(
    n: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> tuple[Any, tuple[list[Any], list[Any]] | None]:
    monkeypatch.setattr("northvaine.radar.structured.get_settings", lambda: SETTINGS)
    doc = parse_notice(n, fetched_at=FETCHED, settings=SETTINGS)
    return doc, structured_evidence(evidence_document_from_sensor(doc))


def test_a_recorded_tender_flows_through_structured_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    doc, out = structured_for(NOTICES["OP00473742"], monkeypatch)
    assert out is not None
    claims, events = out
    assert all(c.source_quote in doc.text.split("\n") for c in claims)
    assert [e.event_type for e in events] == ["tender_published"]
    event = events[0]
    assert event.subject is not None
    assert event.subject.name == "Ministry of Education and Science of Ukraine"
    assert event.subject.country == "UA"
    assert event.occurred_on == DAY
    assert event.group_key == "P171050/MOES-UIHERP-C2-MERGERS-83"
    assert event.slots["deadlines"] == "2026-10-21"
    quotes = {c.source_quote for c in claims}
    assert "Deadline: 2026-10-21" in quotes
    assert "Title [eng]: Procurement of Network Equipment" in quotes


def test_a_recorded_award_flows_through_structured_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    doc, out = structured_for(NOTICES["OP00473716"], monkeypatch)
    assert out is not None
    claims, events = out
    lines = doc.text.split("\n")
    assert all(c.source_quote in lines for c in claims)
    assert [e.event_type for e in events] == ["contract_awarded"]
    event = events[0]
    assert event.subject is not None
    assert event.subject.name == "TEAMS (PVT) LTD"
    assert event.subject.country == "LK"
    assert event.occurred_on == date(2026, 9, 25)  # the decision date, not the notice date
    assert event.slots["value"] == "9812500.00"
    quotes = {c.source_quote for c in claims}
    assert "Winner [eng]: TEAMS (PVT) LTD" in quotes
    assert "Total value: 9812500.00 LKR" in quotes


def test_every_recorded_notice_gives_exact_line_quotes(monkeypatch: pytest.MonkeyPatch) -> None:
    for n in NOTICES.values():
        doc, out = structured_for(n, monkeypatch)
        assert out is not None
        lines = doc.text.split("\n")
        for claim in out[0]:
            assert claim.source_quote in lines
        for event in out[1]:
            assert all(0 <= i < len(out[0]) for i in event.claim_indices)


# ----------------------------------------------------------------------------- search: replay


def sensor_for(exchanges: list, **kw: Any) -> WorldBankSensor:
    client = httpx.AsyncClient(transport=replay_transport(exchanges, match_body=False))
    return WorldBankSensor(client=client, settings=SETTINGS, sleep=no_sleep, **kw)


async def test_replayed_tenders_two_types_and_a_cursor() -> None:
    sensor = sensor_for(load_exchanges(FIXTURES / "tender_1.json"))
    result = await sensor.search(
        SensorQuery(kinds=TENDER, published_from=DAY, published_to=DAY, max_results=12)
    )
    assert len(result.documents) == 12
    assert all(d.source == "worldbank" for d in result.documents)
    assert all(d.meta["notice_kind"] == "tender_published" for d in result.documents)
    assert all(d.published_on == DAY for d in result.documents)
    assert result.next_cursor == "0:12"  # resumes right after the last notice returned
    assert result.truncated is True
    assert result.enumerable is True


async def test_replayed_awards() -> None:
    sensor = sensor_for(load_exchanges(FIXTURES / "award_1.json"))
    result = await sensor.search(
        SensorQuery(kinds=AWARD, published_from=DAY, published_to=DAY, max_results=8)
    )
    assert len(result.documents) == 8
    assert all("Winner [" in d.text for d in result.documents)
    assert result.next_cursor == "0:8"


async def test_a_window_far_before_the_newest_notice_is_found_by_bisection() -> None:
    exchanges = load_exchanges(FIXTURES / "seek_1.json")
    sensor = sensor_for(exchanges)
    day = date(2026, 3, 2)
    result = await sensor.search(
        SensorQuery(kinds=AWARD, published_from=day, published_to=day, max_results=4)
    )
    assert len(result.documents) == 4
    assert {d.published_on for d in result.documents} == {day}
    assert result.next_cursor is not None and result.next_cursor.startswith("0:")
    # one probe for the newest notice, about log2(total) bisection probes, then one page
    assert 10 <= len(exchanges) <= 25


async def test_as_of_drops_notices_not_yet_knowable() -> None:
    sensor = sensor_for(load_exchanges(FIXTURES / "award_1.json"))
    as_of = datetime(2026, 10, 7, 12, 0, tzinfo=UTC)  # notices of the 7th are available on the 8th
    result = await sensor.search(
        SensorQuery(kinds=AWARD, published_from=DAY, published_to=DAY, max_results=8), as_of=as_of
    )
    assert result.documents == []
    assert any("window is empty" in n for n in result.notes)


# ------------------------------------------------------------------------ search: synthetic pages


class FakeApi:
    """Serves newest-first pages of notices per notice type from memory, and records requests."""

    def __init__(self, streams: dict[str, list[dict[str, Any]]]) -> None:
        self.streams = streams
        self.requests: list[dict[str, str]] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        params = dict(request.url.params)
        self.requests.append(params)
        stream = self.streams.get(params["notice_type"], [])
        os_, rows = int(params["os"]), int(params["rows"])
        page = stream[os_ : os_ + rows]
        if params["fl"] == "id,noticedate":
            page = [{"id": n["id"], "noticedate": n["noticedate"]} for n in page]
        body = {"rows": rows, "os": str(os_), "total": str(len(stream)), "procnotices": page}
        return httpx.Response(200, json=body)

    def sensor(self, **settings: Any) -> WorldBankSensor:
        cfg = Settings(_env_file=None, worldbank_page_size=3, **settings)
        client = httpx.AsyncClient(transport=httpx.MockTransport(self.handler))
        return WorldBankSensor(client=client, settings=cfg, sleep=no_sleep)


def stream_of(
    count: int, *, first_day: int = 7, per_day: int = 2, **kw: Any
) -> list[dict[str, Any]]:
    out = []
    for i in range(count):
        day = first_day - i // per_day
        out.append(notice(id=f"OP{i:08d}", noticedate=f"{day:02d}-Oct-2026", **kw))
    return out


async def test_pages_are_read_until_the_window_start() -> None:
    api = FakeApi({"Invitation for Bids": stream_of(12)})  # days 7,7,6,6,5,5,4,4,3,3,2,2
    sensor = api.sensor()
    result = await sensor.search(
        SensorQuery(kinds=TENDER, published_from=date(2026, 10, 5), published_to=date(2026, 10, 7))
    )
    assert [d.external_id for d in result.documents] == [f"OP{i:08d}" for i in range(6)]
    assert result.truncated is False
    assert result.next_cursor is None
    # pages of 3: the second page ends inside the window, the third holds the first older notice
    pages = [r for r in api.requests if r["fl"] != "id,noticedate"]
    assert [r["os"] for r in pages if r["notice_type"] == "Invitation for Bids"] == ["0", "3", "6"]


async def test_the_second_type_is_read_after_the_first() -> None:
    api = FakeApi(
        {
            "Invitation for Bids": stream_of(2),
            "Request for Expression of Interest": [
                notice(id="EOI1", notice_type="Request for Expression of Interest"),
            ],
        }
    )
    result = await api.sensor().search(
        SensorQuery(kinds=TENDER, published_from=DAY, published_to=DAY)
    )
    assert [d.external_id for d in result.documents] == ["OP00000000", "OP00000001", "EOI1"]
    assert [r["notice_type"] for r in api.requests if r["rows"] == "3"] == [
        "Invitation for Bids",
        "Request for Expression of Interest",
    ]


async def test_max_results_stops_exactly_and_the_cursor_resumes_after_it() -> None:
    api = FakeApi({"Invitation for Bids": stream_of(8, first_day=7, per_day=8)})
    sensor = api.sensor()
    query = SensorQuery(kinds=TENDER, published_from=DAY, published_to=DAY, max_results=4)
    first = await sensor.search(query)
    assert [d.external_id for d in first.documents] == [f"OP{i:08d}" for i in range(4)]
    assert first.truncated is True
    assert first.next_cursor == "0:4"
    second = await api.sensor().search(query, cursor=first.next_cursor)
    assert [d.external_id for d in second.documents] == [f"OP{i:08d}" for i in range(4, 8)]
    assert second.next_cursor == "1:0"  # the first type is exhausted; the second is still unread
    assert second.truncated is True


async def test_a_bad_cursor_is_an_error_not_a_restart() -> None:
    api = FakeApi({})
    with pytest.raises(ValueError, match="not a World Bank cursor"):
        await api.sensor().search(SensorQuery(kinds=TENDER), cursor="abc")
    assert api.requests == []


async def test_the_page_cap_truncates_with_a_cursor() -> None:
    api = FakeApi({"Invitation for Bids": stream_of(30, per_day=30)})
    sensor = api.sensor(worldbank_max_pages=2)
    result = await sensor.search(
        SensorQuery(kinds=TENDER, published_from=DAY, published_to=DAY, max_results=100)
    )
    assert len(result.documents) == 6
    assert result.truncated is True
    assert result.next_cursor == "0:6"


async def test_duplicates_across_pages_are_dropped() -> None:
    items = stream_of(4, per_day=4)
    items[3] = dict(items[0])
    api = FakeApi({"Invitation for Bids": items})
    result = await api.sensor().search(
        SensorQuery(kinds=TENDER, published_from=DAY, published_to=DAY)
    )
    assert [d.external_id for d in result.documents] == ["OP00000000", "OP00000001", "OP00000002"]


async def test_individual_method_notices_are_dropped_and_counted() -> None:
    items = [
        notice(id="A", procurement_method_code="INDV"),
        notice(id="B"),
    ]
    api = FakeApi({"Invitation for Bids": items})
    result = await api.sensor().search(
        SensorQuery(kinds=TENDER, published_from=DAY, published_to=DAY)
    )
    assert [d.external_id for d in result.documents] == ["B"]
    assert any("skipped procurement method" in n for n in result.notes)


async def test_countries_and_groups_filter_after_the_page_is_read() -> None:
    items = [
        notice(id="A", project_ctry_name="Kenya", procurement_group="GO"),
        notice(id="B", project_ctry_name="Uganda", procurement_group="GO"),
        notice(id="C", project_ctry_name="Kenya", procurement_group="CW"),
        notice(id="D", project_ctry_name="Eastern and Southern Africa", procurement_group="GO"),
    ]
    api = FakeApi({"Invitation for Bids": items})
    query = SensorQuery(
        kinds=TENDER,
        countries=["KE"],
        codes=["wbgroup:go", "cpv:12345678"],
        published_from=DAY,
        published_to=DAY,
    )
    result = await api.sensor().search(query)
    assert [d.external_id for d in result.documents] == ["A"]
    assert any("wanted countries" in n for n in result.notes)
    assert any("procurement groups" in n for n in result.notes)


async def test_text_is_sent_as_qterm() -> None:
    api = FakeApi({"Invitation for Bids": stream_of(1)})
    await api.sensor().search(
        SensorQuery(kinds=TENDER, text="example", published_from=DAY, published_to=DAY)
    )
    assert all(r["qterm"] == "example" for r in api.requests)


async def test_notices_after_the_window_end_are_skipped() -> None:
    api = FakeApi({"Invitation for Bids": stream_of(4, per_day=1)})  # days 7,6,5,4
    result = await api.sensor().search(
        SensorQuery(kinds=TENDER, published_from=date(2026, 10, 4), published_to=date(2026, 10, 6))
    )
    assert [d.published_on.day for d in result.documents if d.published_on] == [6, 5, 4]
    assert any("outside the window" in n for n in result.notes)


async def test_no_matching_kind_is_a_value_error_before_any_request() -> None:
    api = FakeApi({})
    with pytest.raises(ValueError, match="no query kind"):
        await api.sensor().search(SensorQuery(kinds=[EventType.FACILITY_OPENED]))
    assert api.requests == []


# ----------------------------------------------------------------------------- errors and pacing


def error_sensor(response: httpx.Response, **kw: Any) -> WorldBankSensor:
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: response))
    return WorldBankSensor(client=client, settings=SETTINGS, sleep=no_sleep, **kw)


QUERY = SensorQuery(kinds=TENDER)


async def test_rate_limit_carries_retry_after() -> None:
    sensor = error_sensor(httpx.Response(429, headers={"retry-after": "7"}))
    with pytest.raises(SensorRateLimited) as info:
        await sensor.search(QUERY)
    assert info.value.retry_after == 7.0


async def test_http_error_never_echoes_the_body() -> None:
    sensor = error_sensor(httpx.Response(400, text="secret-detail person@example.org"))
    with pytest.raises(SensorError) as info:
        await sensor.search(QUERY)
    assert "secret-detail" not in str(info.value)
    assert "400" in str(info.value)


async def test_a_backend_error_body_with_status_200_is_an_error() -> None:
    sensor = error_sensor(httpx.Response(200, json={"Debug": True, "error": "400 - boom"}))
    with pytest.raises(SensorError, match="unexpected response shape"):
        await sensor.search(QUERY)


async def test_a_non_json_body_is_an_error() -> None:
    sensor = error_sensor(httpx.Response(200, text="<html>"))
    with pytest.raises(SensorError, match="not JSON"):
        await sensor.search(QUERY)


async def test_requests_are_paced() -> None:
    api = FakeApi({"Invitation for Bids": stream_of(6, per_day=6)})
    waits: list[float] = []

    async def record(seconds: float) -> None:
        waits.append(seconds)

    cfg = Settings(_env_file=None, worldbank_page_size=3)
    client = httpx.AsyncClient(transport=httpx.MockTransport(api.handler))
    sensor = WorldBankSensor(client=client, settings=cfg, sleep=record, min_interval_seconds=5.0)
    await sensor.search(
        SensorQuery(kinds=TENDER, published_from=DAY, published_to=DAY, max_results=50)
    )
    assert len(api.requests) >= 3
    assert len(waits) == len(api.requests) - 1
    assert all(0 < w <= 5.0 for w in waits)
