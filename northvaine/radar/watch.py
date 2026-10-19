"""Watching over time (D110): what is new about a company compared with the client's earlier
runs. Code only, no model, no search. Only runs strictly before the current one count, so a
replay of an old day never sees the future."""

from __future__ import annotations

from datetime import date, timedelta

from pydantic import BaseModel, Field

from northvaine.core.settings import Settings
from northvaine.radar.account import LEVEL_ORDER
from northvaine.radar.models import RadarRun, RankedEntry

__all__ = ["Watch", "developments"]


class Watch(BaseModel):
    first_seen: date
    seen_runs: int
    changes: list[str] = Field(default_factory=list)
    back_in_motion: bool = False


def _words(text: str) -> str:
    return text.replace("_", " ")


def _entries_by_key(run: RadarRun) -> dict[str, RankedEntry]:
    return {e.candidate.key: e for e in run.entries}


def _changes(current: RankedEntry, earlier: list[RankedEntry], latest_day: date) -> list[str]:
    out: list[str] = []
    known = {ev.fingerprint for e in earlier for ev in e.candidate.events}
    for ev in current.candidate.events:
        if ev.fingerprint in known:
            continue
        line = f"New since {latest_day.isoformat()}: {_words(ev.event_type)}"
        if ev.occurred_on:
            line += f", on {ev.occurred_on.isoformat()}"
        out.append(line)
        known.add(ev.fingerprint)

    levels = [e.evidence_level for e in earlier if e.evidence_level in LEVEL_ORDER]
    now = current.evidence_level
    if levels and now in LEVEL_ORDER:
        best = min(levels, key=lambda lv: LEVEL_ORDER[lv])
        if LEVEL_ORDER[now] < LEVEL_ORDER[best]:
            out.append(f"Evidence rose from {_words(best)} to {_words(now)}")

    if current.fit_level and not any(e.fit_level for e in earlier):
        out.append("Its own site now names what you sell")

    if current.label and current.label not in {e.label for e in earlier if e.label}:
        out.append(f"Now labelled {_words(current.label)}")
    return out


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
        changes = _changes(entry, [e for _, e in seen], seen[-1][0])
        out[key] = Watch(
            first_seen=seen[0][0],
            seen_runs=len(seen),
            changes=changes,
            back_in_motion=bool(changes),
        )
    return out
