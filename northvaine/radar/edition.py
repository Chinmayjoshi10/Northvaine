"""The daily edition (D103): every entry gets a label, and a few checked targets lead each day.

- **act now:** a live purchase or award the client can act on (status "bid now" or "contact now").
- **just changed:** something happened to the company itself: set up recently, renamed, a new
  controlling company or a control change, or it started importing the client's codes this year.
- **account to work:** a proven buyer from official trade records with no fresh change.

Labels are computed by code from verified facts only. The edition takes up to
`radar_daily_quota` labelled entries in rank order, at most `radar_daily_mix[label]` of each, and
never pads: a thin day stays thin.
"""

from __future__ import annotations

from datetime import date, timedelta

from northvaine.core.settings import Settings
from northvaine.radar.brief import action_status
from northvaine.radar.models import RadarStream, RankedEntry

__all__ = ["daily_edition", "label_entries"]


def _just_changed(entry: RankedEntry, today: date, settings: Settings) -> str | None:
    facts = entry.candidate.company_register
    recent = timedelta(days=settings.radar_just_changed_days)
    if facts is not None:
        if facts.incorporated and today - facts.incorporated <= timedelta(
            days=settings.radar_new_company_days
        ):
            return f"set up on {facts.incorporated.isoformat()}"
        if facts.renamed_on and today - facts.renamed_on <= recent:
            return f"renamed on {facts.renamed_on.isoformat()}"
        if facts.control_changed_on and today - facts.control_changed_on <= recent:
            owner = f" ({facts.controlled_by[0]})" if facts.controlled_by else ""
            return f"control changed on {facts.control_changed_on.isoformat()}{owner}"
    for event in entry.candidate.events:
        if event.slots.get("new_this_year") is True:
            return f"started importing in {event.slots.get('first_month')}"
    return None


def label_entries(entries: list[RankedEntry], today: date, settings: Settings) -> list[RankedEntry]:
    out: list[RankedEntry] = []
    for entry in entries:
        label: str | None = None
        reason: str | None = None
        status = action_status(entry)
        if status in ("bid now", "contact now"):
            label, reason = "act_now", status
        elif (changed := _just_changed(entry, today, settings)) is not None:
            label, reason = "just_changed", changed
        elif entry.candidate.stream == RadarStream.TRADE and entry.evidence_level == "proven_buyer":
            label, reason = "account_to_work", "a proven buyer of your product codes"
        out.append(entry.model_copy(update={"label": label, "label_reason": reason}))
    return out


def daily_edition(entries: list[RankedEntry], settings: Settings) -> list[RankedEntry]:
    """Up to the quota, in rank order, each label capped by the mix; no padding."""
    taken: list[RankedEntry] = []
    counts: dict[str, int] = {}
    for entry in sorted(entries, key=lambda e: e.rank):
        if entry.label is None:
            continue
        if counts.get(entry.label, 0) >= settings.radar_daily_mix.get(entry.label, 0):
            continue
        counts[entry.label] = counts.get(entry.label, 0) + 1
        taken.append(entry)
        if len(taken) >= settings.radar_daily_quota:
            break
    return taken
