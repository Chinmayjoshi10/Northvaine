"""Where a lead comes from (D125): the opportunity the person sees, the dated facts behind it with
the source of each, and one line to open with. All by code from what the entry already holds: no
model call, no price or term (a person always decides those)."""

from __future__ import annotations

import re
from datetime import date

from pydantic import BaseModel

from northvaine.radar.models import (
    CandidateClaim,
    ClientSpec,
    RadarStream,
    RankedEntry,
)
from northvaine.radar.opportunity import LABEL_WORDS
from northvaine.radar.timing import dated_changes

__all__ = ["Dot", "OpportunityView", "dots", "opening_line", "opportunity_view", "supply_phrase"]

# Plain names for the sources a record can come from; an unknown name is shown as it is.
SOURCE_NAMES = {
    "hmrc": "UK import records (HMRC)",
    "ted": "EU tenders (TED)",
    "fts": "UK Find a Tender",
    "usaspending": "US federal contracts (USAspending)",
    "website": "Company website, read with Tavily",
    "tavily": "Company website, read with Tavily",
    "companies_house": "Companies House",
}
TRADE_SOURCE = "HMRC import records"
CHECK_SOURCE = "Nemotron on Nebius"
CODE_CHECK_SOURCE = "Northvaine's own checks"
_STREAM_KIND = {
    RadarStream.TENDER: "tender",
    RadarStream.AWARD: "contract",
    RadarStream.ANNOUNCEMENT: "news",
    RadarStream.TRADE: "trade",
}
_DATE_SUFFIX = re.compile(r"\s+on \d{4}-\d{2}-\d{2}")


class OpportunityView(BaseModel):
    label: str  # connected | approach_now | relationship | looking | watch
    word: str  # "Approach now"
    words: str  # "Strong intent · Good fit · 3 sources agree"
    why_now: str
    play: str  # project | partner | account


class Dot(BaseModel):
    """One dated or sourced fact about a lead, and where it came from."""

    kind: str  # contract | tender | news | trade | register | website | check
    date: str | None
    line: str
    source: str | None
    url: str | None
    ref: str | None = None


def source_name(raw: str) -> str:
    return SOURCE_NAMES.get(raw.strip().casefold(), raw)


def opportunity_view(entry: RankedEntry) -> OpportunityView | None:
    o = entry.opportunity
    if o is None:
        return None
    return OpportunityView(
        label=o.label,
        word=LABEL_WORDS[o.label],
        words=o.words,
        why_now=o.why_now,
        play=o.play,
    )


def _short(text: str, limit: int = 140) -> str:
    clean = " ".join(text.split())
    if len(clean) <= limit:
        return clean
    return clean[:limit].rsplit(" ", 1)[0].rstrip(",;:. ") + "…"


def _claim_of(refs: list[str], claims: list[CandidateClaim]) -> CandidateClaim | None:
    by_ref = {k.ref: k for k in claims}
    return next((by_ref[r] for r in refs if r in by_ref), None)


def _day(value: date | None) -> str | None:
    return value.isoformat() if value else None


def dots(entry: RankedEntry) -> list[Dot]:
    """Every dated or sourced fact, newest first; undated facts follow the dated ones."""
    c = entry.candidate
    out: list[Dot] = []

    trade = next((k for k in c.claims if k.source_name.casefold() == "hmrc"), None)
    register = next((k for k in c.claims if k.source_name.casefold() == "companies_house"), None)

    for ev in c.events:
        if ev.event_type == "imports_recorded":
            last = str(ev.slots.get("last_month") or "")
            if not last:
                continue
            first = _claim_of(ev.claim_refs, c.claims) or trade
            try:
                when: date | None = date.fromisoformat(f"{last[:7]}-01")
            except ValueError:
                when = None
            out.append(
                Dot(
                    kind="trade",
                    date=_day(when),
                    line=f"Imports recorded through {last[:7]}",
                    source=TRADE_SOURCE,
                    url=first.url if first else None,
                    ref=first.ref if first else None,
                )
            )
            continue
        if ev.occurred_on is None:
            continue
        claim = _claim_of(ev.claim_refs, c.claims)
        out.append(
            Dot(
                kind=_STREAM_KIND[c.stream],
                date=ev.occurred_on.isoformat(),
                line=_short(ev.description),
                source=source_name(claim.source_name) if claim else None,
                url=claim.url if claim else None,
                ref=claim.ref if claim else None,
            )
        )

    for when, line in dated_changes(c):
        if "importing" in line:
            out.append(
                Dot(
                    kind="trade",
                    date=when.isoformat(),
                    line=line,
                    source=TRADE_SOURCE,
                    url=trade.url if trade else None,
                    ref=trade.ref if trade else None,
                )
            )
        else:
            out.append(
                Dot(
                    kind="register",
                    date=when.isoformat(),
                    line=line,
                    source=source_name("companies_house"),
                    url=register.url if register else None,
                    ref=register.ref if register else None,
                )
            )

    site = source_name("website")
    for fit in entry.company_fit:
        out.append(Dot(kind="website", date=None, line=_short(fit.quote), source=site, url=fit.url))
    for judged in entry.judged_lines:
        out.append(
            Dot(kind="website", date=None, line=_short(judged.quote), source=site, url=judged.url)
        )

    by = CODE_CHECK_SOURCE if entry.gate.by == "code" else CHECK_SOURCE
    verdict = entry.gate.demand_reason or entry.gate.reason
    if verdict:
        line = _short(f"Passed the buyer check: {verdict}")
        out.append(Dot(kind="check", date=None, line=line, source=by, url=None))
    sk = entry.skeptic
    if sk.against:
        line = _short(f"Against: {sk.against[0].why}")
        out.append(Dot(kind="check", date=None, line=line, source=by, url=None))
    elif sk.open_questions:
        line = _short(f"Not yet known: {sk.open_questions[0]}")
        out.append(Dot(kind="check", date=None, line=line, source=by, url=None))

    # stable: newest dated first, then the undated in the order built
    dated = sorted((d for d in out if d.date), key=lambda d: d.date or "", reverse=True)
    return dated + [d for d in out if not d.date]


def supply_phrase(spec: ClientSpec | None, offer: str) -> str:
    """What the client supplies, in its own words: the first priority line, else the first offer
    term, else the offer text."""
    if spec is not None:
        if spec.catalogue_lines and spec.catalogue_lines[0].name.strip():
            return spec.catalogue_lines[0].name.strip()
        term = next((t.strip() for t in spec.offer_terms if t.strip()), "")
        if term:
            return term
    return offer.strip()


# The reason to call, in words a salesperson would write. Keyed by the opening words of
# `Opportunity.why_now`: generic event types and register changes, never an industry.
_NEWS_WORDS = (
    ("contract awarded", "winning the contract"),
    ("tender published", "the new tender"),
    ("facility opened", "the new opening"),
    ("market entry", "the move into a new market"),
    ("expansion", "the expansion"),
    ("product launch", "the launch"),
    ("hiring surge", "the growth of your team"),
)
_CHANGE_WORDS = (
    ("Control changed", "the change of ownership"),
    ("A charge (new finance)", "the new investment"),
    ("It started importing", "that you have started importing"),
    ("It added a new product line", "the new range you are adding"),
    ("It came back to importing", "that you are buying again"),
    ("Its imports are rising", "your growing imports"),
    ("It was renamed", "the new company name"),
    ("Its registered office moved", "the move to a new office"),
    ("It was incorporated", "the new company"),
)


def _reason(why_now: str, table: tuple[tuple[str, str], ...], default: str) -> str:
    low = why_now.strip().casefold()
    return next((words for key, words in table if low.startswith(key.casefold())), default)


def opening_line(entry: RankedEntry, supply: str) -> str | None:
    """One line the client could open with, by play. Facts and a sample offer only: never a price,
    a discount, a date or a term."""
    o = entry.opportunity
    if o is None or not supply:
        return None
    # A product name mid-sentence: lower-case its first letter, unless it is an acronym.
    if len(supply) > 1 and supply[0].isupper() and not supply[1].isupper():
        supply = supply[0].lower() + supply[1:]
    if o.play == "project":
        news = _reason(o.why_now, _NEWS_WORDS, "the project")
        return (
            f"Congratulations on {news}. We supply {supply}; could we send samples for the project?"
        )
    if o.play == "partner":
        # Only a dated, sourced change may be "noticed"; with none, the line claims nothing.
        change = _reason(o.why_now, _NEWS_WORDS + _CHANGE_WORDS, "") if o.why_now else ""
        if not change:
            return (
                f"We make {supply} and work with distributors like you; "
                "would a sample range be useful?"
            )
        return (
            f"We noticed {change}. We make {supply} and work with distributors; "
            "would a sample range be useful?"
        )
    product = next(
        (
            k.source_quote.split(": imported")[0]
            for k in entry.candidate.claims
            if k.source_quote.startswith("Commodity ")
        ),
        None,
    )
    imports = _short(product, 80) if product else f"goods like {supply}"
    return (
        f"You already import {imports}. Would a second source, with samples to compare, "
        "be worth a look?"
    )
