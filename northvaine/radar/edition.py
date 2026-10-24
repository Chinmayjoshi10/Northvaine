"""The daily edition (D103): every entry gets a label, and a few checked targets lead each day.

- **act now:** a live purchase or award the client can act on (status "bid now" or "contact now").
- **just changed:** something happened to the company itself: a control change, a rename, set
  up recently, or it started importing the client's codes this year. More changes rank higher.
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


def _changes(entry: RankedEntry, today: date, settings: Settings) -> list[str]:
    """Every dated change to the company itself, strongest kinds first."""
    facts = entry.candidate.company_register
    recent = timedelta(days=settings.radar_just_changed_days)
    found: list[str] = []
    if facts is not None:
        if facts.control_changed_on and today - facts.control_changed_on <= recent:
            owner = f" ({facts.controlled_by[0]})" if facts.controlled_by else ""
            found.append(f"control changed on {facts.control_changed_on.isoformat()}{owner}")
        if facts.renamed_on and today - facts.renamed_on <= recent:
            found.append(f"renamed on {facts.renamed_on.isoformat()}")
        new_company = timedelta(days=settings.radar_new_company_days)
        if facts.incorporated and today - facts.incorporated <= new_company:
            found.append(f"set up on {facts.incorporated.isoformat()}")
    for event in entry.candidate.events:
        if event.slots.get("new_this_year") is True:
            found.append(f"started importing in {event.slots.get('first_month')}")
            break
    return found


# D125: an assessed entry's label follows its opportunity, so the edition and the ranking agree.
_FROM_OPPORTUNITY = {
    "connected": "act_now",
    "approach_now": "act_now",
    "relationship": "just_changed",
    "looking": "just_changed",
}


def label_entries(entries: list[RankedEntry], today: date, settings: Settings) -> list[RankedEntry]:
    out: list[RankedEntry] = []
    for entry in entries:
        label: str | None = None
        reason: str | None = None
        strength = 0
        status = action_status(entry)
        opportunity = entry.opportunity
        if opportunity is not None:
            # Ranked by opportunity already: no strength, so the edition keeps that order.
            label = _FROM_OPPORTUNITY.get(opportunity.label)
            if label is not None:
                reason = opportunity.why_now or opportunity.words
            elif (
                entry.candidate.stream == RadarStream.TRADE
                and entry.evidence_level == "proven_buyer"
            ):
                label, reason = "account_to_work", "a proven buyer of your product codes"
        elif status in ("bid now", "contact now"):
            label, reason = "act_now", status
        elif changes := _changes(entry, today, settings):
            label, reason, strength = "just_changed", "; ".join(changes), len(changes)
        elif entry.candidate.stream == RadarStream.TRADE and entry.evidence_level == "proven_buyer":
            label, reason = "account_to_work", "a proven buyer of your product codes"
        out.append(
            entry.model_copy(
                update={"label": label, "label_reason": reason, "label_strength": strength}
            )
        )
    return out


def daily_edition(entries: list[RankedEntry], settings: Settings) -> list[RankedEntry]:
    """Up to the quota, each label capped by the mix; no padding. Within the edition, entries
    with more dated changes come first, then rank (a rename plus a new owner plus new imports
    beats a company that only started importing)."""
    if any(e.opportunity is not None for e in entries):
        # D125: ranked by opportunity already, so the edition is simply the best ones in rank
        # order; the watch list never fills a slot.
        ranked = sorted(entries, key=lambda e: e.rank)
        best = [e for e in ranked if e.opportunity is not None and e.opportunity.label != "watch"]
        # D134: leads the senior review passed come first; an unreviewed one only fills a gap.
        reviewed = [e for e in best if any(r.startswith("Reviewed:") for r in e.rank_reasons)]
        if reviewed:
            best = [*reviewed, *(e for e in best if e not in reviewed)]
        # D129: the best of each kind first (connected, approach now, relationship, looking for
        # it), so a day mixes a project, a partner and a buyer; then the rest in rank order.
        firsts: list[RankedEntry] = []
        for kind in ("connected", "approach_now", "relationship", "looking"):
            pick = next((e for e in best if e.opportunity and e.opportunity.label == kind), None)
            if pick is not None:
                firsts.append(pick)
        rest = [e for e in best if e not in firsts]
        return sorted([*firsts, *rest][: settings.radar_daily_quota], key=lambda e: e.rank)
    taken: list[RankedEntry] = []
    counts: dict[str, int] = {}
    for entry in sorted(entries, key=lambda e: (-e.label_strength, e.rank)):
        if entry.label is None:
            continue
        if counts.get(entry.label, 0) >= settings.radar_daily_mix.get(entry.label, 0):
            continue
        counts[entry.label] = counts.get(entry.label, 0) + 1
        taken.append(entry)
        if len(taken) >= settings.radar_daily_quota:
            break
    return taken
