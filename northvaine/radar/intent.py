"""Intent searches written from the client's own answers, one market at a time (D126).

The client said which projects or events make a customer need it (`need_triggers`), what it
sells (`offer_terms`, its priority catalogue lines), who buys (`buyer_roles`), how it sells
(`channel`) and where (`markets`). From those words alone, every market gets two web searches:

- a **project** search: one of the client's triggers + its product + "contractor appointed";
- a **partner change** search: one of its buyer roles + its product + the words of a change that
  makes a company need a new supplier (expansion, new showroom, new branch, new range).

The results go through the ordinary pipeline (evidence ledger, off-target filter, gate, skeptic),
so nothing here can make a lead on its own. No industry word is written here.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from northvaine.core.standards import iso2_to_name
from northvaine.sensors.base import SensorQuery

__all__ = [
    "intent_queries",
    "market_news_queries",
    "partner_matrix_queries",
    "partner_queries",
    "trade_covered",
]

_PROJECT_WORDS = "contractor appointed"
# One change per market, rotating: a search with all of them at once finds none well.
_CHANGES = ("expansion", "opens new showroom", "new branch", "launches new range")
# Generic trade words for a channel partner (any industry): only these get change searches.
_CHANNEL_WORDS = (
    "distribut", "dealer", "wholesal", "merchant", "importer", "retailer",
    "reseller", "stockist", "showroom", "supplier", "agent",
)  # fmt: skip


# D152: channel roles searched for a client that sells through partners and named none
_GENERIC_CHANNEL = ("distributors", "dealers")


def _product(spec: Any) -> str:
    """The client's product in its broadest own words, for finding projects: its first offer
    term. Priority lines are for ranking fit; they are too narrow to search the web with."""
    terms = [t for t in spec.offer_terms if t.strip()]
    return terms[0] if terms else ""


def _channel_roles(spec: Any) -> list[str]:
    return [r for r in spec.buyer_roles if any(w in r.casefold() for w in _CHANNEL_WORDS)]


def intent_queries(spec: Any, as_of: date, days: int, per_market: int = 2) -> list[SensorQuery]:
    """Web searches for every market, newest `days` only. Triggers and roles rotate across
    markets, so each market asks a different question and the whole set covers more of them.
    With `per_market=1` each market asks one question a day, project and partner on alternate
    days, so both are covered every two days at half the searches."""
    product = _product(spec)
    triggers = [t for t in getattr(spec, "need_triggers", []) if t.strip()]
    roles = [r for r in spec.buyer_roles if r.strip()]
    partners = _channel_roles(spec)
    if not product or not spec.markets:
        return []
    out: list[SensorQuery] = []
    for i, country in enumerate(spec.markets):
        place = (iso2_to_name(country) or country).title()
        asks: list[str] = []
        if triggers:
            asks.append(f"{triggers[i % len(triggers)]} {product} {_PROJECT_WORDS} {place}")
        elif roles:
            asks.append(f"new {roles[i % len(roles)]} project {product} {place}")
        if partners and spec.channel != "direct":
            role = partners[i % len(partners)]
            asks.append(f"{role} {product} {_CHANGES[i % len(_CHANGES)]} {place}")
        if per_market == 1 and len(asks) == 2:
            asks = [asks[(as_of.toordinal() + i) % 2]]
        for text in asks[:per_market]:
            out.append(
                SensorQuery(
                    text=text,
                    countries=[country],
                    languages=["en"],
                    published_from=as_of - timedelta(days=days),
                    published_to=as_of,
                    max_results=5,
                )
            )
    return out


def trade_covered(spec: Any) -> set[str]:
    """Countries the client's import-record sensors cover: any sensor query with an `hs:` code."""
    covered: set[str] = set()
    for queries in (getattr(spec, "sensors", None) or {}).values():
        for q in queries:
            if any(str(c).startswith("hs:") for c in q.codes):
                covered.update(c.upper() for c in q.countries)
    return covered


def partner_queries(
    spec: Any, as_of: date, per_market: int = 1, all_markets: bool = False
) -> list[SensorQuery]:
    """Partner discovery (D136): for each market without import records, search for the
    companies' own websites (`<channel role> <product> showrooms <country>`). No date filter: a
    distributor's site is not news. Nothing for a client that sells direct. `all_markets`
    (a first radar, D140) searches markets with import records too."""
    del as_of  # no date window; kept so the call reads like `intent_queries`
    product = _product(spec)
    partners = _channel_roles(spec)
    if not product or not partners or spec.channel == "direct":
        return []
    covered = set() if all_markets else trade_covered(spec)
    out: list[SensorQuery] = []
    for i, country in enumerate(spec.markets):
        if country.upper() in covered:
            continue
        place = (iso2_to_name(country) or country).title()
        for j in range(max(per_market, 1)):
            role = partners[(i + j) % len(partners)]
            out.append(
                SensorQuery(
                    text=f"{role} {product} showrooms {place}",
                    countries=[country],
                    languages=["en"],
                    max_results=5,
                )
            )
    return out


def partner_matrix_queries(spec: Any, limit: int, results: int) -> list[SensorQuery]:
    """Account-first discovery (D151, plan B S3): companies' own sites, found by each of the
    client's buyer roles (up to 3) with each of its own product words (up to 2), in every market,
    `<role> <product words> <country>`. Markets take turns, so a run with many markets still asks
    each one something; at most `limit` searches. No fixed shop word: "showrooms" fitted retail and
    found nothing for wholesale, machinery or food. Nothing for a client with no roles or words.

    A client that sells through partners is searched for its channel first: its own trade roles,
    else generic ones ("distributors", "dealers"). A product word alone finds the product's makers
    (a first run found only competitors), and an end buyer's own site rarely names a product it
    buys, while a stockist's site states what it stocks (D152)."""
    stated = [r for r in spec.buyer_roles if r.strip()]
    channel = [r for r in stated if any(w in r.casefold() for w in _CHANNEL_WORDS)]
    if spec.channel != "direct" and len(channel) < 2:
        channel += [g for g in _GENERIC_CHANNEL if g not in channel][: 2 - len(channel)]
    others = [r for r in stated if r not in channel]
    roles = (channel + others)[:3] if spec.channel != "direct" else stated[:3]
    words = [t for t in spec.offer_terms if t.strip()][:2]
    if not roles or not words or not spec.markets:
        return []
    pairs = [(r, w) for w in words for r in roles]
    out: list[SensorQuery] = []
    for turn in range(len(pairs)):
        for country in spec.markets:
            if len(out) >= limit:
                return out
            role, word = pairs[turn]
            place = (iso2_to_name(country) or country).title()
            out.append(
                SensorQuery(
                    text=f"{role} {word} {place}",
                    countries=[country],
                    languages=["en"],
                    max_results=results,
                )
            )
    return out


def market_news_queries(
    spec: Any, as_of: date, days: int, per_market: int = 1, limit: int = 6
) -> list[SensorQuery]:
    """Market news (D140): the client's own need triggers in each market, newest `days` only,
    without the product word (`<trigger> <country>`, e.g. "<kind of project> <country>"). Project
    news rarely names a supplier's product; it names the project and the companies behind it.
    The results still pass the off-target filter, which keeps news only when its own quotes name
    one of the client's triggers or products (D128), then the gate and the skeptic. Triggers
    rotate across markets so the set covers more of them. Every market gets its first search
    before any gets a second, and the whole set stops at `limit` (search credits)."""
    triggers = [t for t in getattr(spec, "need_triggers", []) if t.strip()]
    if not triggers or not spec.markets or per_market < 1:
        return []
    out: list[SensorQuery] = []
    for j in range(per_market):
        for i, country in enumerate(spec.markets):
            if len(out) >= limit:
                return out
            place = (iso2_to_name(country) or country).title()
            trigger = triggers[(i * per_market + j) % len(triggers)]
            out.append(
                SensorQuery(
                    text=f"{trigger} {place}",
                    countries=[country],
                    languages=["en"],
                    published_from=as_of - timedelta(days=days),
                    published_to=as_of,
                    max_results=5,
                )
            )
    return out
