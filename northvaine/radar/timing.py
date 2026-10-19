"""Timing signals (D111): what is changing at a company right now, from free official records and
data the run already holds. Pure code: no model call, no search, no names.

A signal counts when its date is within `days` of the run day (and not in the future)."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from northvaine.radar.models import Candidate

__all__ = ["timing_signals"]


def timing_signals(candidate: Candidate, as_of: date, days: int) -> list[str]:
    """Short lines in our own words, each with its date, newest first."""
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
    earliest = as_of - timedelta(days=days)
    inside = sorted(((w, t) for w, t in dated if earliest <= w <= as_of), reverse=True)
    return [t for _, t in inside]
