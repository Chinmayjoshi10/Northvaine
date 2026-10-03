"""parse_date and parse_datetime on every shape in the research notes (T3.0a)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta, timezone

import pytest

from northvaine.sensors.dates import parse_date, parse_datetime


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2026-04-01+02:00", date(2026, 4, 1)),  # the calendar date as written
        ("2026-04-01-05:00", date(2026, 4, 1)),
        ("2026-08-10Z", date(2026, 8, 10)),  # PF2: a bare Z offset on winner-decision-date
        ("2026-06-17T15:00:00+03:00", date(2026, 6, 17)),
        ("2026-06-17T23:30:00-05:00", date(2026, 6, 17)),  # not shifted to UTC
        ("2026-06-17T15:00:00Z", date(2026, 6, 17)),
        ("2026-06-17T15:00:00.123Z", date(2026, 6, 17)),
        ("2026-04-01", date(2026, 4, 1)),
        ("  2026-04-01  ", date(2026, 4, 1)),
        ("Tue, 11 Mar 2025 17:00:00 GMT", date(2025, 3, 11)),
    ],
)
def test_parse_date_shapes(raw: str, expected: date) -> None:
    assert parse_date(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        None,
        "",
        "   ",
        "garbage",
        "2026-13-01",
        "2026-02-30",
        "01/04/2026",
        "2026-04-01+99:00",
        "x" * 500,
    ],
)
def test_parse_date_returns_none_without_raising(raw: str | None) -> None:
    assert parse_date(raw) is None


def test_parse_date_ignores_non_strings() -> None:
    assert parse_date(20260401) is None  # type: ignore[arg-type]


def test_parse_datetime_with_offset() -> None:
    got = parse_datetime("2026-06-17T15:00:00+03:00")
    assert got == datetime(2026, 6, 17, 12, 0, tzinfo=UTC)
    assert got is not None and got.utcoffset() == timedelta(hours=3)
    assert got.tzinfo == timezone(timedelta(hours=3))


def test_parse_datetime_with_z() -> None:
    assert parse_datetime("2026-06-17T15:00:00Z") == datetime(2026, 6, 17, 15, 0, tzinfo=UTC)


def test_parse_datetime_bare_z_date() -> None:
    assert parse_datetime("2026-08-10Z") == datetime(2026, 8, 10, 0, 0, tzinfo=UTC)


def test_parse_datetime_date_with_offset() -> None:
    got = parse_datetime("2026-04-01+02:00")
    assert got is not None and got.utcoffset() == timedelta(hours=2)
    assert got.date() == date(2026, 4, 1)


def test_parse_datetime_rfc1123() -> None:
    assert parse_datetime("Tue, 11 Mar 2025 17:00:00 GMT") == datetime(
        2025, 3, 11, 17, 0, tzinfo=UTC
    )


def test_parse_datetime_never_returns_naive() -> None:
    # No offset is no guess: plain date and local time give None, never a naive datetime.
    assert parse_datetime("2026-04-01") is None
    assert parse_datetime("2026-04-01T10:00:00") is None
    for raw in [
        "2026-04-01+02:00",
        "2026-04-01Z",
        "2026-06-17T15:00:00Z",
        "Tue, 11 Mar 2025 17:00:00 GMT",
        "Tue, 11 Mar 2025 17:00:00 -0000",
    ]:
        got = parse_datetime(raw)
        assert got is None or got.tzinfo is not None, raw


@pytest.mark.parametrize("raw", [None, "", "garbage", "2026-13-45T00:00:00Z"])
def test_parse_datetime_returns_none_without_raising(raw: str | None) -> None:
    assert parse_datetime(raw) is None
