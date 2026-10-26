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

__all__ = ["intent_queries", "partner_queries", "trade_covered"]

_PROJECT_WORDS = "contractor appointed"
# One change per market, rotating: a search with all of them at once finds none well.
_CHANGES = ("expansion", "opens new showroom", "new branch", "launches new range")
# Generic trade words for a channel partner (any industry): only these get change searches.
_CHANNEL_WORDS = (
    "distribut", "dealer", "wholesal", "merchant", "importer", "retailer",
    "reseller", "stockist", "showroom", "supplier", "agent",
)  # fmt: skip


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


def partner_queries(spec: Any, as_of: date, per_market: int = 1) -> list[SensorQuery]:
    """Partner discovery (D136): for each market without import records, search for the
    companies' own websites (`<channel role> <product> showrooms <country>`). No date filter: a
    distributor's site is not news. Nothing for a client that sells direct."""
    del as_of  # no date window; kept so the call reads like `intent_queries`
    product = _product(spec)
    partners = _channel_roles(spec)
    if not product or not partners or spec.channel == "direct":
        return []
    covered = trade_covered(spec)
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
