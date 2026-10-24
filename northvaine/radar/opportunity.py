"""Opportunities: why to talk to a company now, and how strongly (D125).

Every ranked entry gets an assessment from the facts it already carries, by code only:

- a play: project (a tender, contract or project news), partner (a channel partner that sells the
  client's kind of product) or account (a proven buyer of the product);
- three factors, each 0-3 and said in words: intent (how strong and fresh the about-to-buy
  signal is), fit (how well it matches what the client sells) and confidence (how many
  independent kinds of source agree);
- a label the person sees, top to bottom: connected, approach now, build a relationship,
  looking for it, watch list.

Nothing here names an industry: the facts come from official records, the company's own site and
the client's own data.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Literal

from northvaine.radar.account import size_rank
from northvaine.radar.brief import _trade_slots, names_term, names_trigger
from northvaine.radar.models import Opportunity, RadarStream, RankedEntry
from northvaine.radar.timing import dated_changes, trade_changes

__all__ = ["LABEL_ORDER", "Opportunity", "assess", "order_opportunities"]

Label = Literal["connected", "approach_now", "relationship", "looking", "watch"]
Play = Literal["project", "partner", "account"]

LABEL_ORDER: dict[str, int] = {
    "connected": 0,
    "approach_now": 1,
    "relationship": 2,
    "looking": 3,
    "watch": 4,
}
LABEL_WORDS = {
    "connected": "Connected",
    "approach_now": "Approach now",
    "relationship": "Build a relationship",
    "looking": "Looking for it",
    "watch": "Watch list",
}
_INTENT_WORDS = ("No new signal", "Weak intent", "Clear intent", "Strong intent")
_FIT_WORDS = ("Fit unknown", "Some fit", "Good fit", "Strong fit")
_PROJECT_STREAMS = (RadarStream.TENDER, RadarStream.AWARD, RadarStream.ANNOUNCEMENT)
# The opening words of changes read from the import record rather than the register.
_TRADE_LINES = (
    "It started importing",
    "It added a new product line",
    "It came back to importing",
    "Its imports are rising",
)
# The opening words timing.dated_changes uses for the changes that weigh more.
_STRONG_CHANGES = (
    "Control changed",
    "A charge (new finance)",
    "It started importing",
    "It added a new product line",  # D131: changes in the import record itself
    "It came back to importing",
    "Its imports are rising",
)


def _freshness(when: date, today: date, strong_days: int, clear_days: int) -> int:
    """3 inside strong_days, 2 inside clear_days, 1 older but within a year, 0 otherwise."""
    if when > today:
        return 0
    age = (today - when).days
    if age <= strong_days:
        return 3
    if age <= clear_days:
        return 2
    return 1 if age <= 365 else 0


def _signals(entry: RankedEntry, today: date) -> list[tuple[int, date, str, str]]:
    """(strength, date, line, kind) for every dated about-to-buy signal on the entry."""
    c = entry.candidate
    out: list[tuple[int, date, str, str]] = []
    for event in c.events:
        if event.occurred_on is None or event.event_type == "imports_recorded":
            continue
        # A contract, tender or project is the strongest kind of intent; full strength while fresh.
        strength = _freshness(event.occurred_on, today, 90, 180)
        kind = "record" if c.stream in (RadarStream.TENDER, RadarStream.AWARD) else "news"
        if strength:
            what = event.event_type.replace("_", " ")
            out.append((strength, event.occurred_on, f"{what} on {event.occurred_on}", kind))
    for when, line in [*dated_changes(c), *trade_changes(c)]:
        # A company change opens a window but is weaker than a project. A new owner, new finance
        # or a first import says more than a new name or a moved office (a hint only).
        base = 2 if line.startswith(_STRONG_CHANGES) else 1
        age = (today - when).days
        strength = base if 0 <= age <= 90 else (base - 1 if 0 <= age <= 180 else 0)
        if strength:
            kind = "trade" if line.startswith(_TRADE_LINES) else "register"
            out.append((strength, when, line, kind))
    return out


def assess(entry: RankedEntry, as_of: date, spec: Any) -> Opportunity:
    """The entry's opportunity, from the facts it already holds and the client's own words. Pure."""
    c = entry.candidate
    signals = _signals(entry, as_of)
    best = max(signals, default=None, key=lambda s: (s[0], s[1]))
    intent = best[0] if best else 0
    if len({s[3] for s in signals if s[0] >= 2}) >= 2:
        intent = min(3, intent + 1)  # two different kinds of clear change agree

    # Fit is proof that the company deals in what the client sells: its own site (or, for a
    # contract or news item, its title or its name) names it. An import record of the client's
    # codes proves a purchase but not which of the client's products, so on its own it is "some".
    terms = {t.casefold() for t in spec.offer_terms if t.strip()}
    named = bool(terms) and names_term(c.name, terms, prefix=True)
    on_site = entry.fit_level == "stated" or bool(entry.judged_lines)
    on_record = c.stream in _PROJECT_STREAMS and (entry.requirement == "stated" or named)
    # A named company's project of the kind the client said needs it fits too; a tender does not
    # (no contractor yet, and general works say nothing about the product) (D128).
    kind = (
        c.stream != RadarStream.TENDER and c.stream in _PROJECT_STREAMS and names_trigger(c, spec)
    )
    on_record = on_record or kind
    some = (
        c.stream == RadarStream.TRADE
        or entry.fit_level == "related"
        or entry.requirement == "related"
    )
    fit = 2 if on_site or on_record else (1 if some else 0)
    if fit >= 2 and (entry.matched_lines or entry.fit_distinctive or c.like_customers):
        fit = 3
    if entry.site_role == "makes":
        fit = 0  # a possible competitor (D124)

    kinds = {s.value for s in c.streams} | {c.stream.value}
    if c.company_register is not None and any(s[3] == "register" for s in signals):
        kinds.add("register")
    if entry.company_fit or entry.judged_lines:
        kinds.add("website")
    if any(s[3] == "news" for s in signals):
        kinds.add("news")
    confidence = len(kinds)

    partner = entry.gate.partner or (entry.site_role == "resells" and spec.channel != "direct")
    # A company found on the web that resells the product is a partner, not a project (D133);
    # official tenders and awards stay projects.
    record = c.stream in (RadarStream.TENDER, RadarStream.AWARD)
    if c.stream in _PROJECT_STREAMS and (record or not partner):
        play: Play = "project"
    elif partner:
        play = "partner"
    else:
        play = "account"

    # A project is worth a call only when its record or the company's own site names what the
    # client sells: a fresh tender for general works is a project to watch, not a lead (a live
    # run filled the top with public works tenders that never named the product).
    label: Label
    weak_project = play == "project" and fit < 2
    # D129: a big channel partner that clearly fits is worth a relationship even with no news; an
    # update that leads to buying (intent) ranks it higher. Big = larger filed accounts, or it
    # imports the product month after month.
    facts = c.company_register
    months = int(_trade_slots(c).get("months_active") or 0)
    big = size_rank(facts.accounts_type if facts else None) >= 3 or months >= 6
    # Abroad there are no UK accounts or import records to size a company: a partner whose own
    # site shows it resells the product counts on fit alone (D133).
    abroad = facts is None and (c.country or "") != "GB" and entry.site_role == "resells"
    standing = play == "partner" and fit >= 2 and (big or abroad) and entry.site_role != "makes"
    if standing and intent < 2:
        label = "relationship"
    elif intent == 0 or entry.site_role == "makes" or (intent == 1 and fit < 2) or weak_project:
        label = "watch"  # nothing new, a competitor, a hint at a weak fit, a vague project
    elif intent >= 2 and confidence >= 3 and fit >= 2:
        label = "connected"
    else:
        label = {"project": "approach_now", "partner": "relationship", "account": "looking"}[play]

    sources = f"{confidence} source{'s' if confidence != 1 else ''} agree"
    words = f"{_INTENT_WORDS[intent]} · {_FIT_WORDS[fit]} · {sources}"
    return Opportunity(
        label=label,
        play=play,
        intent=intent,
        fit=fit,
        confidence=confidence,
        latest=max((s[1] for s in signals), default=None),
        why_now=best[2] if best else "",
        words=words,
    )


def order_opportunities(entries: list[RankedEntry], as_of: date, spec: Any) -> list[RankedEntry]:
    """Every entry assessed and ordered: label, then intent, fit, confidence, the newest signal,
    then the earlier order. A possible competitor always goes last. Ranks renumbered 1..n and the
    assessment is the first rank reason."""
    assessed = [(e, assess(e, as_of, spec)) for e in sorted(entries, key=lambda e: e.rank)]
    oldest = as_of - timedelta(days=36500)

    def key(item: tuple[RankedEntry, Opportunity]) -> tuple[object, ...]:
        e, o = item
        return (
            e.site_role == "makes",
            LABEL_ORDER[o.label],
            -o.intent,
            -o.fit,
            -o.confidence,
            -((o.latest or oldest) - oldest).days,
            e.rank,
        )

    out: list[RankedEntry] = []
    for n, (e, o) in enumerate(sorted(assessed, key=key), start=1):
        line = f"{LABEL_WORDS[o.label]}: {o.words}" + (f" ({o.why_now})" if o.why_now else "")
        reasons = [
            line,
            *[r for r in e.rank_reasons if not r.startswith(tuple(LABEL_WORDS.values()))],
        ]
        out.append(e.model_copy(update={"rank": n, "opportunity": o, "rank_reasons": reasons}))
    return out
