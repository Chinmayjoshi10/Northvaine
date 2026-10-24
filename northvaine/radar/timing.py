"""Timing signals (D111): what is changing at a company right now, from free official records and
data the run already holds. Pure code: no model call, no search, no names.

A signal counts when its date is within `days` of the run day (and not in the future)."""

from __future__ import annotations

from datetime import date, timedelta
from itertools import pairwise
from typing import Any

from northvaine.radar.models import Candidate

__all__ = ["dated_changes", "timing_signals", "trade_changes"]


def timing_signals(candidate: Candidate, as_of: date, days: int) -> list[str]:
    """Short lines in our own words, each with its date, newest first."""
    earliest = as_of - timedelta(days=days)
    inside = sorted(
        ((w, t) for w, t in dated_changes(candidate) if earliest <= w <= as_of), reverse=True
    )
    return [t for _, t in inside]


def dated_changes(candidate: Candidate) -> list[tuple[date, str]]:
    """Every dated change the register and the trade record show, any age, unordered (D125)."""
    from northvaine.radar.brief import _trade_slots  # late: brief imports the radar models

    facts = candidate.company_register
    dated: list[tuple[date, str]] = []
    if facts is not None:
        dated.extend(
            (when, f"{what} on {when.isoformat()}")
            for when, what in (
                (facts.charge_created_on, "A charge (new finance) was registered"),
                (facts.office_moved_on, "Its registered office moved"),
                (facts.control_changed_on, "Control changed"),
                (facts.renamed_on, "It was renamed"),
                (facts.incorporated, "It was incorporated"),
            )
            if when is not None
        )
    slots: dict[str, Any] = _trade_slots(candidate)
    if slots.get("new_this_year"):
        raw = str(slots.get("first_month") or "")
        try:
            first = date.fromisoformat(f"{raw[:7]}-01") if raw else None
        except ValueError:
            first = None
        if first is not None:
            dated.append((first, f"It started importing (first record {raw[:7]})"))
    return dated


def _month(label: str) -> int | None:
    """'2026-07' -> 202607 (a month id that sorts and subtracts by month), or None."""
    try:
        year, month = int(label[:4]), int(label[5:7])
    except (ValueError, IndexError):
        return None
    return year * 12 + month - 1 if 1 <= month <= 12 else None


def _day(mid: int) -> date:
    return date(mid // 12, mid % 12 + 1, 1)


def trade_changes(candidate: Candidate) -> list[tuple[date, str]]:
    """What the official import record shows changing, month by month (D131). Pure code:

    - a new product line: a product code first imported in the company's last 3 months, while it
      already imported other codes before - a new range is when a buyer looks for a new supplier;
    - back after a gap: importing again after 3 or more months with none;
    - imports rising: imported in each of its last 3 months, after at most 1 of the 3 before.
    Each line is dated at the month it shows, so freshness is judged like any other signal."""
    from northvaine.radar.brief import _trade_slots  # late: brief imports the radar models

    slots: dict[str, Any] = _trade_slots(candidate)
    months = sorted({m for m in (_month(x) for x in slots.get("months") or []) if m is not None})
    if not months:
        return []
    last = months[-1]
    out: list[tuple[date, str]] = []
    code_months = slots.get("code_months") or {}
    if isinstance(code_months, dict):
        for code, labels in sorted(code_months.items()):
            mine = sorted({m for m in (_month(x) for x in labels or []) if m is not None})
            if mine and last - mine[0] < 3 and months[0] < mine[0]:
                out.append(
                    (
                        _day(mine[0]),
                        f"It added a new product line (code {code}, first imported "
                        f"{_day(mine[0]).isoformat()[:7]})",
                    )
                )
    for earlier, later in pairwise(months):
        if later - earlier > 3 and last - later < 3:
            out.append(
                (
                    _day(later),
                    f"It came back to importing in {_day(later).isoformat()[:7]} "
                    f"after {later - earlier - 1} months without",
                )
            )
    recent = sum(1 for m in months if last - m < 3)
    before = sum(1 for m in months if 3 <= last - m < 6)
    if recent == 3 and before <= 1 and months[0] <= last - 3:
        out.append(
            (
                _day(last),
                f"Its imports are rising: every month of the last 3, after "
                f"{before} of the 3 before",
            )
        )
    return out
