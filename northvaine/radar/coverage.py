"""Where a radar has official buyer records, said before and after a run (D158, plan B 5.2).

A radar is strongest where official records name buyers (import records, public contracts) and
thinner where it can only read company websites and news. Saying so up front sets an honest
expectation: a short list in a market without records is the data, not a fault. Code only,
from the sensors the client spec already uses; no industry words.
"""

from __future__ import annotations

from typing import Any

__all__ = ["coverage", "coverage_line"]

# What each official source gives, in plain words. Web search is not an official record.
_OFFICIAL = {
    "hmrc": "import records",
    "fts": "public contracts",
    "ted": "EU public contracts",
    "usaspending": "federal contracts",
    "worldbank": "development-bank contracts",
}
# Read for every lead in this market by the register check (D103), whatever the sensors.
_REGISTERS = {"GB": "company register"}


def coverage(spec: Any) -> tuple[dict[str, list[str]], list[str]]:
    """({market: [official sources]}, [markets with websites and news only]), markets in the
    client's order."""
    markets = [m for m in (getattr(spec, "markets", None) or []) if m]
    found: dict[str, list[str]] = {m: [] for m in markets}
    for name, queries in (getattr(spec, "sensors", None) or {}).items():
        what = _OFFICIAL.get(name)
        if what is None:
            continue
        for query in queries:
            countries = getattr(query, "countries", None)
            if countries is None and isinstance(query, dict):
                countries = query.get("countries")
            for country in countries or []:
                if country in found and what not in found[country]:
                    found[country].append(what)
    for market, register in _REGISTERS.items():
        if found.get(market):
            found[market].append(register)
    official = {m: found[m] for m in markets if found[m]}
    web_only = [m for m in markets if not found[m]]
    return official, web_only


def coverage_line(spec: Any) -> str | None:
    """One honest sentence, or None for a client with no markets."""
    official, web_only = coverage(spec)
    if not official and not web_only:
        return None
    groups: dict[tuple[str, ...], list[str]] = {}
    for market, sources in official.items():
        groups.setdefault(tuple(sources), []).append(market)
    parts = [f"{', '.join(ms)} ({', '.join(src)})" for src, ms in groups.items()]
    out = []
    if parts:
        out.append("Official buyer records: " + "; ".join(parts) + ".")
    if web_only:
        out.append(
            f"Company websites and news only: {', '.join(web_only)}, so expect fewer proven "
            "leads there."
        )
    return " ".join(out)
