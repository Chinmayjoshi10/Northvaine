"""Watching over time (D110): what is new about a company compared with the client's earlier
runs. Code only, no model, no search. Only runs strictly before the current one count, so a
replay of an old day never sees the future."""

from __future__ import annotations

import re
from datetime import date, timedelta

from pydantic import BaseModel, Field

from northvaine.core.models import EventType
from northvaine.core.settings import Settings
from northvaine.radar.account import LEVEL_ORDER
from northvaine.radar.models import RadarRun, RankedEntry

__all__ = ["Watch", "developments"]

_IMPORTS = EventType.IMPORTS_RECORDED.value
# the commodity lines our own import sensor writes (as in fit.py)
_COMMODITY = re.compile(r"commodity (\d{6,10})")


class Watch(BaseModel):
    first_seen: date
    seen_runs: int
    changes: list[str] = Field(default_factory=list)
    back_in_motion: bool = False


def _words(text: str) -> str:
    return text.replace("_", " ")


def _entries_by_key(run: RadarRun) -> dict[str, RankedEntry]:
    return {e.candidate.key: e for e in run.entries}


def _codes(entries: list[RankedEntry]) -> set[str]:
    """Product codes in the import records of these entries (the record's commodity lines)."""
    return {
        code
        for e in entries
        for ev in e.candidate.events
        if ev.event_type == _IMPORTS
        for code in _COMMODITY.findall(ev.description or "")
    }


def _changes(
    current: RankedEntry, earlier: list[RankedEntry], latest_day: date
) -> tuple[list[str], list[str]]:
    """(moves, notes): what the company did since the last look, and what we only learned."""
    out: list[str] = []
    info: list[str] = []
    # An import record is a standing record: a new month of the same imports gives it a new
    # fingerprint, but importing again is not news. A product code not imported before is.
    new_codes = sorted(_codes([current]) - _codes(earlier)) if _codes(earlier) else []
    if new_codes:
        out.append(
            f"New since {latest_day.isoformat()}: imports a product code it did not before "
            f"({', '.join(new_codes[:3])})"
        )
    known = {ev.fingerprint for e in earlier for ev in e.candidate.events}
    for ev in current.candidate.events:
        if ev.event_type == _IMPORTS or ev.fingerprint in known:
            continue
        known.add(ev.fingerprint)
        # An event dated before the last look is one we only found now: worth listing, but the
        # company did not move. Undated events count as new.
        if ev.occurred_on is not None and ev.occurred_on < latest_day:
            info.append(f"Newly found: {_words(ev.event_type)}, on {ev.occurred_on.isoformat()}")
            continue
        line = f"New since {latest_day.isoformat()}: {_words(ev.event_type)}"
        if ev.occurred_on:
            line += f", on {ev.occurred_on.isoformat()}"
        out.append(line)

    levels = [e.evidence_level for e in earlier if e.evidence_level in LEVEL_ORDER]
    now = current.evidence_level
    if levels and now in LEVEL_ORDER:
        best = min(levels, key=lambda lv: LEVEL_ORDER[lv])
        # rising to company fit only means our site check reached it this time (see below)
        if LEVEL_ORDER[now] < LEVEL_ORDER[best] and now != "company_fit":
            out.append(f"Evidence rose from {_words(best)} to {_words(now)}")

    # Company fit is not listed: which sites get read changes night to night (D108 caps it), so
    # a fit appearing says more about our checks than about the company moving.
    if current.label and current.label not in {e.label for e in earlier if e.label}:
        out.append(f"Now labelled {_words(current.label)}")
    return out, info


def developments(
    current: RadarRun, earlier: list[RadarRun], settings: Settings
) -> dict[str, Watch]:
    """Watch rows keyed by candidate key, for every company of `current` seen in an earlier run
    inside `radar_watch_days`. A company never seen before gets no row."""
    today = current.as_of.date()
    oldest = today - timedelta(days=settings.radar_watch_days)
    usable = sorted((r for r in earlier if oldest <= r.as_of.date() < today), key=lambda r: r.as_of)
    maps = [(r.as_of.date(), _entries_by_key(r)) for r in usable]
    out: dict[str, Watch] = {}
    for entry in current.entries:
        key = entry.candidate.key
        seen = [(day, m[key]) for day, m in maps if key in m]
        if not seen:
            continue
        moves, notes = _changes(entry, [e for _, e in seen], seen[-1][0])
        out[key] = Watch(
            first_seen=seen[0][0],
            seen_runs=len(seen),
            changes=[*moves, *notes],
            back_in_motion=bool(moves),
        )
    return out
