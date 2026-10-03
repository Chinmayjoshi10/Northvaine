"""validate_notice_dates and available_at_for_publication (T3.4)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from northvaine.sensors.base import DateFlag
from northvaine.sensors.dates import available_at_for_publication, validate_notice_dates

PUB = date(2026, 3, 10)


def flags(publication=PUB, deadlines=(), decisions=(), lag=365):
    return validate_notice_dates(
        publication, list(deadlines), list(decisions), extreme_lag_days=lag
    )


def test_clean_notice_has_no_flags():
    assert flags(deadlines=[PUB + timedelta(days=30)]) == []
    assert flags(decisions=[PUB - timedelta(days=3)]) == []


def test_deadline_before_publication_reproduces_the_probe_minus_31_days():
    # D29: the probe saw a deadline 31 days before its notice's publication date.
    assert flags(deadlines=[PUB - timedelta(days=31)]) == [DateFlag.DEADLINE_BEFORE_PUBLICATION]


def test_decision_after_publication():
    assert flags(decisions=[PUB + timedelta(days=1)]) == [DateFlag.DECISION_AFTER_PUBLICATION]


def test_extreme_lag_uses_the_argument_threshold():
    far = PUB - timedelta(days=242)  # D29: award publication lags up to 242 days
    assert flags(decisions=[far], lag=365) == []
    assert flags(decisions=[far], lag=200) == [DateFlag.EXTREME_LAG]
    assert flags(deadlines=[PUB + timedelta(days=400)]) == [DateFlag.EXTREME_LAG]


def test_missing_publication():
    assert flags(publication=None, deadlines=[PUB]) == [DateFlag.MISSING_PUBLICATION]


def test_unparseable_is_a_none_entry():
    assert DateFlag.UNPARSEABLE in flags(deadlines=[None])
    assert DateFlag.UNPARSEABLE in flags(decisions=[None, PUB])


def test_multiple_values_counts_distinct_dates_only():
    d = PUB + timedelta(days=10)
    assert flags(deadlines=[d, d, d]) == []
    assert flags(deadlines=[d, d + timedelta(days=1)]) == [DateFlag.MULTIPLE_VALUES]
    assert flags(decisions=[PUB, PUB - timedelta(days=2)]) == [DateFlag.MULTIPLE_VALUES]


def test_never_drops_or_changes_inputs():
    deadlines = [PUB - timedelta(days=31)]
    decisions = [PUB + timedelta(days=5)]
    before = (list(deadlines), list(decisions))
    result = flags(deadlines=deadlines, decisions=decisions)
    assert (deadlines, decisions) == before
    assert result == [DateFlag.DEADLINE_BEFORE_PUBLICATION, DateFlag.DECISION_AFTER_PUBLICATION]


def test_available_at_is_midnight_utc_after_the_lag():
    assert available_at_for_publication(date(2026, 4, 1)) == datetime(2026, 4, 2, tzinfo=UTC)
    assert available_at_for_publication(date(2026, 4, 1), lag_days=3) == datetime(
        2026, 4, 4, tzinfo=UTC
    )
    assert available_at_for_publication(date(2026, 12, 31)) == datetime(2027, 1, 1, tzinfo=UTC)
