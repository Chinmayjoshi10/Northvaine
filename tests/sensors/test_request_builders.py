"""ted.build_request and tavily.build_search_request (T3.0a)."""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, timedelta, timezone

import pytest

from northvaine.core.models import EventType
from northvaine.core.settings import Settings
from northvaine.sensors import tavily, ted
from northvaine.sensors.base import SensorQuery

SETTINGS = Settings(_env_file=None)
TENDER = EventType.TENDER_PUBLISHED
AWARD = EventType.CONTRACT_AWARDED


def q(**kw: object) -> SensorQuery:
    kw.setdefault("kinds", [TENDER])
    return SensorQuery(**kw)  # type: ignore[arg-type]


# ----------------------------------------------------------------------------- TED


def test_ted_constants() -> None:
    assert ted.TED_MAX_LIMIT == 250
    assert ted.TED_KIND_TO_NOTICE_TYPES == {TENDER: ("cn-standard",), AWARD: ("can-standard",)}


def test_ted_safe_fields_carry_no_contact_data() -> None:
    banned = re.compile(r"email|tel|fax|person|contact-point|ubo|internet-address")
    assert ted.TED_SAFE_FIELDS
    for field in ted.TED_SAFE_FIELDS:
        assert not banned.search(field), field
    assert "procedure-identifier" in ted.TED_SAFE_FIELDS
    assert len(set(ted.TED_SAFE_FIELDS)) == len(ted.TED_SAFE_FIELDS)


def test_ted_minimal_request() -> None:
    body = ted.build_request(q(), settings=SETTINGS)
    assert body == {
        "query": "notice-type=cn-standard",
        "fields": list(ted.TED_SAFE_FIELDS),
        "limit": 50,
        "page": 1,
    }


def test_ted_clause_order_and_single_value_uses_equals() -> None:
    body = ted.build_request(
        q(
            codes=["cpv:12345678"],
            countries=["DE"],
            published_from=date(2026, 1, 2),
            published_to=date(2026, 3, 4),
        ),
        settings=SETTINGS,
    )
    assert body["query"] == (
        "notice-type=cn-standard AND classification-cpv=12345678 AND buyer-country=DEU"
        " AND publication-date>=20260102 AND publication-date<=20260304"
    )


def test_ted_several_values_use_in() -> None:
    body = ted.build_request(
        q(kinds=[TENDER, AWARD], codes=["cpv:111", "cpv:222"], countries=["DE", "GB"]),
        settings=SETTINGS,
    )
    assert body["query"] == (
        "notice-type IN (cn-standard can-standard) AND classification-cpv IN (111 222)"
        " AND buyer-country IN (DEU GBR)"
    )


def test_ted_duplicates_are_removed_and_order_kept() -> None:
    body = ted.build_request(
        q(kinds=[AWARD, TENDER, AWARD], countries=["FR", "DE", "FR"]), settings=SETTINGS
    )
    assert (
        body["query"] == "notice-type IN (can-standard cn-standard) AND buyer-country IN (FRA DEU)"
    )


def test_ted_as_of_caps_the_upper_bound_by_the_lag() -> None:
    as_of = datetime(2026, 5, 10, 3, 0, tzinfo=UTC)
    body = ted.build_request(q(), as_of=as_of, settings=SETTINGS)
    assert body["query"].endswith("publication-date<=20260509")


def test_ted_as_of_uses_the_utc_date() -> None:
    plus9 = timezone(timedelta(hours=9))
    as_of = datetime(2026, 5, 10, 3, 0, tzinfo=plus9)  # 2026-05-09 18:00 UTC
    body = ted.build_request(q(), as_of=as_of, settings=SETTINGS)
    assert body["query"].endswith("publication-date<=20260508")


def test_ted_as_of_uses_the_configured_lag() -> None:
    settings = Settings(_env_file=None, ted_availability_lag_days=3)
    body = ted.build_request(q(), as_of=datetime(2026, 5, 10, tzinfo=UTC), settings=settings)
    assert body["query"].endswith("publication-date<=20260507")


def test_ted_upper_bound_is_the_smaller_of_published_to_and_as_of() -> None:
    as_of = datetime(2026, 5, 10, tzinfo=UTC)
    earlier = ted.build_request(q(published_to=date(2026, 5, 1)), as_of=as_of, settings=SETTINGS)
    later = ted.build_request(q(published_to=date(2026, 6, 1)), as_of=as_of, settings=SETTINGS)
    assert earlier["query"].endswith("publication-date<=20260501")
    assert later["query"].endswith("publication-date<=20260509")


def test_ted_naive_as_of_is_rejected() -> None:
    with pytest.raises(ValueError):
        ted.build_request(q(), as_of=datetime(2026, 5, 10), settings=SETTINGS)


def test_ted_limit_is_capped_at_250_and_page_is_passed() -> None:
    assert ted.build_request(q(max_results=250), settings=SETTINGS)["limit"] == 250
    assert ted.build_request(q(max_results=7), page=3, settings=SETTINGS)["limit"] == 7
    assert ted.build_request(q(max_results=7), page=3, settings=SETTINGS)["page"] == 3
    big = Settings(_env_file=None, sensor_max_results=1000)
    assert big.sensor_max_results == 1000  # the cap in the builder is TED's own, not the setting
    assert ted.TED_MAX_LIMIT == 250


def test_ted_ignores_text_and_non_cpv_codes() -> None:
    plain = ted.build_request(q(codes=["cpv:111"]), settings=SETTINGS)
    noisy = ted.build_request(
        q(codes=["naics:238990", "cpv:111", "unspsc:1234"], text="free words here"),
        settings=SETTINGS,
    )
    assert plain == noisy
    assert "naics" not in noisy["query"] and "free words" not in noisy["query"]


def test_ted_no_mappable_kind_is_a_value_error() -> None:
    with pytest.raises(ValueError):
        ted.build_request(q(kinds=[]), settings=SETTINGS)
    with pytest.raises(ValueError):
        ted.build_request(q(kinds=[EventType.HIRING_SURGE]), settings=SETTINGS)


def test_ted_unmappable_kinds_are_skipped_when_another_maps() -> None:
    body = ted.build_request(q(kinds=[EventType.HIRING_SURGE, AWARD]), settings=SETTINGS)
    assert body["query"] == "notice-type=can-standard"


def test_ted_body_has_only_the_confirmed_keys() -> None:
    body = ted.build_request(q(), settings=SETTINGS)
    assert set(body) == {"query", "fields", "limit", "page"}


# ----------------------------------------------------------------------------- Tavily


def tq(**kw: object) -> SensorQuery:
    kw.setdefault("text", "some words")
    return SensorQuery(**kw)  # type: ignore[arg-type]


def test_tavily_canonical_body() -> None:
    body, notes = tavily.build_search_request(tq(), settings=SETTINGS)
    assert body == {
        "query": "some words",
        "topic": "general",
        "search_depth": "basic",
        "max_results": 20,
        "include_raw_content": "text",
        "include_published_date": True,
        "include_usage": True,
    }
    assert notes == []


def test_tavily_max_results_is_capped_at_20() -> None:
    assert (
        tavily.build_search_request(tq(max_results=250), settings=SETTINGS)[0]["max_results"] == 20
    )
    assert tavily.build_search_request(tq(max_results=5), settings=SETTINGS)[0]["max_results"] == 5


def test_tavily_date_range() -> None:
    body, _ = tavily.build_search_request(
        tq(published_from=date(2026, 1, 2), published_to=date(2026, 3, 4)), settings=SETTINGS
    )
    assert body["start_date"] == "2026-01-02" and body["end_date"] == "2026-03-04"
    body, _ = tavily.build_search_request(tq(published_from=date(2026, 1, 2)), settings=SETTINGS)
    assert body["start_date"] == "2026-01-02" and "end_date" not in body


def test_tavily_one_country_is_sent_as_a_lowercase_english_name() -> None:
    body, notes = tavily.build_search_request(tq(countries=["GB"]), settings=SETTINGS)
    assert body["country"] == "united kingdom"
    assert notes == []


def test_tavily_several_countries_are_omitted_with_a_note() -> None:
    body, notes = tavily.build_search_request(tq(countries=["GB", "DE"]), settings=SETTINGS)
    assert "country" not in body
    assert len(notes) == 1 and "country" in notes[0]


def test_tavily_no_country_no_note() -> None:
    body, notes = tavily.build_search_request(tq(), settings=SETTINGS)
    assert "country" not in body and notes == []


def test_tavily_never_sends_days_auto_parameters_or_a_key() -> None:
    settings = Settings(_env_file=None, tavily_api_key="fake-key")
    body, _ = tavily.build_search_request(
        tq(countries=["GB"], published_from=date(2026, 1, 1)), settings=settings
    )
    for key in ("days", "auto_parameters", "api_key", "key", "authorization"):
        assert key not in body
    assert "fake-key" not in repr(body)


@pytest.mark.parametrize("text", [None, "", "   "])
def test_tavily_needs_text(text: str | None) -> None:
    with pytest.raises(ValueError):
        tavily.build_search_request(SensorQuery(text=text), settings=SETTINGS)
