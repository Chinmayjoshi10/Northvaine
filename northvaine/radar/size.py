"""How big a company is, from sentences on its own site (D150, plan B step S4).

The client wants big buyers first (large distributors, importers with many outlets). Outside the
UK there are no filed accounts or import records to size a company, but its own pages usually say
"24 branches", "over 300 employees" or "15 showrooms across the state". Code reads those sentences;
each kept one becomes a verified claim quoting the page (rule 2), so a size is never inferred.

Tiers (same scale as `account.size_rank`): 1 small, 2 mid, 3 large.
- places (branches, stores, showrooms, outlets, warehouses, depots, offices, locations): 10 or
  more 3, 3 to 9 2, 2 1;
- people (employees, staff, people, team members, colleagues): 250 or more 3, 50 to 249 2,
  10 to 49 1.
Only generic English nouns; no industry word. Years, percentages, prices, ratings and product
counts never count: the number must sit right before one of the nouns above.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

__all__ = ["SizeFact", "best_size", "size_facts"]

_PLACES = (
    "branches|branch locations|stores|shops|showrooms|outlets|warehouses|depots|"
    "distribution centres|distribution centers|offices|locations|sites"
)
_PEOPLE = "employees|staff|people|team members|colleagues|workers"
# "over 300", "more than 1,200", "300+", "24"; then up to two adjectives ("retail", "UK-wide")
_NUMBER = r"(?:(?:over|more than|nearly|almost|around|some)\s+)?(\d{1,3}(?:,\d{3})*|\d+)(\+)?"
_GAP = r"(?:\s+[A-Za-z-]+){0,2}?"
_PLACE_RE = re.compile(rf"\b{_NUMBER}{_GAP}\s+({_PLACES})\b", re.IGNORECASE)
_PEOPLE_RE = re.compile(rf"\b{_NUMBER}{_GAP}\s+({_PEOPLE})\b", re.IGNORECASE)
# a sentence: no longer than this, so a size fact is a readable quote
_MAX_SENTENCE = 300
_SENTENCES = re.compile(r"[^.!?\n]+[.!?]?")


@dataclass(frozen=True)
class SizeFact:
    tier: int  # 1 small, 2 mid, 3 large
    words: str  # "24 branches"
    sentence: str  # the page's own sentence, verbatim


def _tier(count: int, kind: str) -> int:
    if kind == "places":
        return 3 if count >= 10 else 2 if count >= 3 else 1 if count >= 2 else 0
    return 3 if count >= 250 else 2 if count >= 50 else 1 if count >= 10 else 0


def size_facts(text: str) -> list[SizeFact]:
    """Every sentence of `text` that states a size, strongest first."""
    found: list[SizeFact] = []
    for m in _SENTENCES.finditer(text):
        sentence = m.group(0).strip()
        if not sentence or len(sentence) > _MAX_SENTENCE:
            continue
        for kind, pattern in (("places", _PLACE_RE), ("people", _PEOPLE_RE)):
            for hit in pattern.finditer(sentence):
                count = int(hit.group(1).replace(",", ""))
                tier = _tier(count, kind)
                if tier:
                    noun = hit.group(3).lower()
                    found.append(
                        SizeFact(tier, f"{hit.group(1)}{hit.group(2) or ''} {noun}", sentence)
                    )
    found.sort(key=lambda f: -f.tier)
    return found


def best_size(texts: list[str]) -> SizeFact | None:
    """The strongest size fact over several pages, or None."""
    facts = [f for t in texts for f in size_facts(t)]
    return max(facts, key=lambda f: f.tier) if facts else None
