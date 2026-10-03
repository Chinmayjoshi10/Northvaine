"""Date parsing and validation for sensors (D27-D29, D38).

`parse_date` and `parse_datetime` are pure and never raise: unreadable input gives None.
`validate_notice_dates` and `available_at_for_publication` are filled in by T3.4.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

from northvaine.sensors.base import DateFlag

# 2026-04-01, 2026-04-01+02:00, 2026-08-10Z, 2026-06-17T15:00:00+03:00, ...Z, fractional seconds.
_ISO = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})"
    r"(?:[T ](\d{2}):(\d{2})(?::(\d{2})(?:[.,]\d+)?)?)?"
    r"\s*(Z|[+-]\d{2}(?::?\d{2})?)?$",
    re.IGNORECASE,
)


def _offset(text: str | None) -> timezone | None:
    if text is None:
        return None
    if text.upper() == "Z":
        return UTC
    sign = -1 if text[0] == "-" else 1
    digits = text[1:].replace(":", "")
    hours, minutes = int(digits[:2]), int(digits[2:4] or 0)
    if hours > 23 or minutes > 59:
        raise ValueError("offset out of range")
    return timezone(sign * timedelta(hours=hours, minutes=minutes))


def _parse_iso(value: str) -> tuple[datetime, bool] | None:
    """(datetime as written, has_timezone) or None."""
    match = _ISO.match(value)
    if not match:
        return None
    year, month, day, hour, minute, second, offset = match.groups()
    try:
        tz = _offset(offset)
        moment = datetime(
            int(year),
            int(month),
            int(day),
            int(hour or 0),
            int(minute or 0),
            int(second or 0),
            tzinfo=tz,
        )
    except ValueError:
        return None
    return moment, tz is not None


def _parse_rfc1123(value: str) -> datetime | None:
    try:
        moment = parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError):
        return None
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


def parse_date(value: str | None) -> date | None:
    """The calendar date as written, ignoring any offset ('2026-04-01+02:00' -> 2026-04-01).

    Accepts ISO dates and datetimes (with `Z` or `+HH:MM`) and RFC 1123. None, empty and
    unreadable input give None.
    """
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    parsed = _parse_iso(text)
    if parsed is not None:
        return parsed[0].date()
    moment = _parse_rfc1123(text)
    return moment.date() if moment is not None else None


def parse_datetime(value: str | None) -> datetime | None:
    """A timezone-aware datetime, or None. Never naive: a value with no offset gives None."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    parsed = _parse_iso(text)
    if parsed is not None:
        moment, aware = parsed
        return moment if aware else None
    return _parse_rfc1123(text)


def validate_notice_dates(
    publication: date | None,
    deadlines: Sequence[date],
    decisions: Sequence[date],
    *,
    extreme_lag_days: int,
) -> list[DateFlag]:
    """Flag impossible or suspicious date combinations; never correct them (D29). T3.4."""
    raise NotImplementedError("T3.4")


def available_at_for_publication(d: date, *, lag_days: int = 1) -> datetime:
    """00:00 UTC of `d + lag_days`: when a published notice counts as knowable (D36). T3.4."""
    raise NotImplementedError("T3.4")
