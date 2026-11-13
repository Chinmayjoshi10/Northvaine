"""A company's country, read by code from its own web address and its own words (D149, plan B S2).

A record with no country cannot be shown as a lead (D148). Many companies found on the web carry
no country in their record although their own site says where they are. This module reads three
things, all code, no model and no new fetch:

1. the country ending of its own web address (`.co.uk`, `.fr`, `.in`); endings sold for generic use
   (`.io`, `.ai`, `.co`, ...) say nothing about a country;
2. a postal address format in a verified quote from its own site: a UK postcode, or a US state
   abbreviation followed by a ZIP code;
3. the name of exactly one of the client's markets in a verified quote from its own site.

The first that answers wins, and the entry carries a line saying where the country came from.
Nothing here is an industry word; the country names come from the standards table.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit

from northvaine.core.standards import iso2_to_name
from northvaine.radar.models import RankedEntry

__all__ = ["country_of", "resolve_countries"]

# Two-letter endings sold to anyone, used for their look, not their country.
_GENERIC_ENDINGS = frozenset(
    {"io", "ai", "co", "me", "tv", "fm", "ly", "to", "ws", "cc", "gg", "so", "sh", "is", "it"}
)
_ENDING_ALIASES = {"uk": "GB"}
_SHORT_NAMES = {"US": ("usa", "u.s.a.", "united states"), "GB": ("uk", "u.k.", "united kingdom")}
_UK_POSTCODE = re.compile(r"\b[A-Z]{1,2}\d[A-Z\d]?\s+\d[A-Z]{2}\b")
# the two-letter state codes of a US postal address, then a ZIP code
_US_ADDRESS = re.compile(
    r"\b(?:AL|AK|AZ|AR|CA|CO|CT|DE|FL|GA|HI|ID|IL|IN|IA|KS|KY|LA|ME|MD|MA|MI|MN|MS|MO|MT|NE|NV"
    r"|NH|NJ|NM|NY|NC|ND|OH|OK|OR|PA|RI|SC|SD|TN|TX|UT|VT|VA|WA|WV|WI|WY|DC)\s+\d{5}(?:-\d{4})?\b"
)


def _host(url: str | None) -> str:
    if not url:
        return ""
    return (urlsplit(url if "//" in url else f"https://{url}").hostname or "").lower()


def country_from_host(url: str | None) -> str | None:
    host = _host(url)
    if "." not in host:
        return None
    ending = host.rsplit(".", 1)[1]
    if ending in _ENDING_ALIASES:
        return _ENDING_ALIASES[ending]
    if len(ending) != 2 or ending in _GENERIC_ENDINGS:
        return None
    code = ending.upper()
    try:
        iso2_to_name(code)
    except KeyError:
        return None
    return code


def _names(code: str) -> set[str]:
    try:
        names = {iso2_to_name(code).casefold()}
    except KeyError:
        return set()
    return names | set(_SHORT_NAMES.get(code, ()))


def country_from_text(texts: list[str], markets: list[str]) -> tuple[str, str] | None:
    """(country, how) from the company's own verified words, or None."""
    joined = "\n".join(texts)
    if _UK_POSTCODE.search(joined):
        return "GB", "a UK postcode on its own site"
    if _US_ADDRESS.search(joined):
        return "US", "a US address on its own site"
    low = joined.casefold()
    named = {
        m
        for m in markets
        if any(re.search(rf"(?<![\w.]){re.escape(n)}(?![\w])", low) for n in _names(m))
    }
    if len(named) == 1:
        code = named.pop()
        return code, "its own site names the country"
    return None


def _own_site_texts(entry: RankedEntry) -> list[str]:
    """Verified quotes taken from the company's own site (its fit sentences and claims there)."""
    site = _host(entry.company_site).removeprefix("www.")
    texts = [f.quote for f in entry.company_fit]
    if site:
        for claim in entry.candidate.claims:
            if _host(claim.url).removeprefix("www.").endswith(site):
                texts.append(claim.source_quote)
    return texts


def country_of(entry: RankedEntry, markets: list[str]) -> tuple[str, str] | None:
    """(country, where it came from) for an entry whose record has none, or None."""
    code = country_from_host(entry.company_site)
    if code:
        return code, "its web address"
    return country_from_text(_own_site_texts(entry), markets)


def resolve_countries(entries: list[RankedEntry], spec: Any) -> list[RankedEntry]:
    """Every entry without a country gets one when its own site shows it; the rank reasons say
    how. Entries that already have a country are untouched."""
    markets = list(getattr(spec, "markets", None) or [])
    out = []
    for e in entries:
        if e.candidate.country:
            out.append(e)
            continue
        found = country_of(e, markets)
        if found is None:
            out.append(e)
            continue
        code, how = found
        out.append(
            e.model_copy(
                update={
                    "candidate": e.candidate.model_copy(update={"country": code}),
                    "rank_reasons": [*e.rank_reasons, f"Country: {code}, from {how}"],
                }
            )
        )
    return out
