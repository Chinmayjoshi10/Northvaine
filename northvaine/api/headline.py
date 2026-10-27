"""Plain words for a lead (D137): a headline, why it matters to the client, built by code.

The owner reads one line: who did what, when, with the number if there is one; then why it matters
to them, in their own product words. Every word comes from verified facts already on the lead (the
official record, the register, the company's own site) and from the client's own data - nothing is
written freely, nothing is invented, no codes or scores. Industry-neutral.
"""

from __future__ import annotations

import re

from northvaine.core.settings import Settings, get_settings
from northvaine.radar.models import RankedEntry
from northvaine.radar.opportunity import record_line

__all__ = ["display_name", "headline", "why_you"]

_SIZE = {"full": "large", "group": "large", "medium": "mid-size", "small": "small"}


def display_name(name: str, settings: Settings | None = None) -> str:
    """'ACME TRADING LIMITED' -> 'Acme Trading': readable case, legal form dropped."""
    cfg = settings or get_settings()
    words = name.split()
    forms = {f.casefold().strip(".") for f in cfg.radar_legal_forms}
    while words and words[-1].casefold().strip(".,") in forms:
        words.pop()
    text = " ".join(words) or name
    if not text.isupper():
        return text
    small = {
        "de",
        "des",
        "du",
        "la",
        "le",
        "les",
        "of",
        "and",
        "the",
        "et",
        "y",
        "di",
        "der",
        "und",
    }
    out = [w.title() for w in text.split()]
    return " ".join([out[0], *(w.lower() if w.lower() in small else w for w in out[1:])])


def _client_words(entry: RankedEntry, terms: list[str]) -> list[str]:
    """The client's own offer words that the import record's product lines name, in order."""
    text = " ".join(
        c.source_quote for c in entry.candidate.claims if c.source_quote.startswith("Commodity ")
    ).casefold()
    return [t for t in terms if t.strip() and t.casefold() in text]


def _products(entry: RankedEntry) -> list[str]:
    """Short product names from the import record lines ('Commodity 12345678 (Product, ...)')."""
    out: list[str] = []
    for claim in entry.candidate.claims:
        quote = claim.source_quote
        if not quote.startswith("Commodity ") or "(" not in quote:
            continue
        desc = quote.split("(", 1)[1]
        desc = re.split(r",? (?:incl|excl)\.|\(|, with|, in |, whether|, of ", desc)[0].strip(" ,")
        if desc and desc not in out:
            out.append(desc if len(desc) <= 60 else desc[:60].rsplit(" ", 1)[0])
    return out


def _lower_first(text: str) -> str:
    return text[:1].lower() + text[1:] if text[:2] != text[:2].upper() else text


def headline(
    entry: RankedEntry, terms: list[str] | None = None, settings: Settings | None = None
) -> str | None:
    """One sentence: who did what, when. None for entries with no opportunity."""
    o = entry.opportunity
    if o is None:
        return None
    name = display_name(entry.candidate.name, settings)
    why = o.why_now.strip()
    products = _products(entry)
    own = _client_words(entry, terms or [])
    product = " and ".join(own[:2]) if own else (products[0].lower() if products else "")
    record = [
        e for e in entry.candidate.events if e.occurred_on and e.event_type != "imports_recorded"
    ]
    if entry.candidate.stream.value in ("award", "tender") and record:
        latest = max(record, key=lambda e: e.occurred_on)
        line = record_line(latest, entry.candidate.claims)
        if line:
            return f"{name} {_lower_first(line)}." if line.startswith("Won") else f"{line}."
    if why.startswith("It added a new product line"):
        month = re.search(r"first imported (\d{4}-\d{2})", why)
        what = f": {product}" if product else ""
        return f"{name} started importing a new product line{what}" + (
            f" (first in {month.group(1)})." if month else "."
        )
    if why.startswith("Its imports are rising"):
        of = f" of {product}" if product else ""
        return f"{name}'s imports{of} are rising: every month of the last 3."
    if why.startswith("It came back to importing"):
        return f"{name} {_lower_first(why.replace('It came back', 'came back'))}."
    changes = (
        ("Control changed on ", "changed owner on "),
        ("A charge (new finance) was registered on ", "registered new finance on "),
        ("It was renamed on ", "changed its name on "),
        ("Its registered office moved on ", "moved its registered office on "),
        ("It started importing (first record ", "started importing your kind of product ("),
        ("It was incorporated on ", "was set up on "),
    )
    for start, words in changes:
        if why.startswith(start):
            return f"{name} {words}{why[len(start) :]}."
    if why:
        return f"{name}: {why}."
    facts = entry.candidate.company_register
    size = _SIZE.get((facts.accounts_type or "").lower(), "") if facts else ""
    role = "distributor" if entry.site_role == "resells" else "buyer"
    lead = f"{name}: a {size + ' ' if size else ''}{role}"
    if product:
        return f"{lead} that imports {product} through the year."
    return f"{lead} whose own site sells your kind of product."


def why_you(entry: RankedEntry, terms: list[str] | None = None) -> str | None:
    """Why it matters to the client, in the client's own product words."""
    line = entry.matched_lines[0] if entry.matched_lines else ""
    line = line.split(":")[0].split(" (")[0].strip()  # the line's name, not its list of products
    stated = [f.term for f in entry.company_fit if f.level == "stated"]
    fit = stated[0] if stated else ""
    own = _client_words(entry, terms or [])
    products = [" and ".join(own[:2])] if own else _products(entry)
    if fit and line:
        return f"Their own site sells {fit}: your {_lower_first(line)} line."
    if fit:
        return f"Their own site sells {fit}, which you supply."
    if products:
        return f"They import {products[0].lower()}, which you supply."
    if line:
        return f"The work calls for your {_lower_first(line)} line."
    return None
