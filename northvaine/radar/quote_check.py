"""Quote check: find a claim's `source_quote` inside `documents.text` (T4.2, D48).

Runs in code before any LLM check (CLAUDE.md #2). Two modes: `extracted` (normalized exact match,
then a stdlib `difflib` window at `quote_match_min_ratio`, minimum `quote_min_chars`) for LLM
drafts, and `structured` (the quote must equal one whole line of the text, no normalization, no
fuzzy, no minimum) for structured records. `QuoteMatch.offset` indexes the ORIGINAL text.
"""

from __future__ import annotations

from northvaine.core.models import QuoteMatch, QuoteMode
from northvaine.core.settings import Settings

__all__ = ["find_quote", "normalize_text", "quote_contains"]


def normalize_text(text: str) -> str:
    """NFKC, curly quotes to straight, dashes to a hyphen, runs of whitespace to one space."""
    raise NotImplementedError("T4.2")


def find_quote(
    text: str,
    quote: str,
    *,
    mode: QuoteMode = QuoteMode.EXTRACTED,
    settings: Settings | None = None,
) -> QuoteMatch:
    """Locate `quote` in `text`; a miss carries `reason` (`quote_not_found`, `quote_too_short`)."""
    raise NotImplementedError("T4.2")


def quote_contains(quote: str, fragment: str) -> bool:
    """True when `fragment` is a substring of `quote` after `normalize_text` and case folding.

    Used to ground event fields (date, subject, country, slots) in a verified quote (D50).
    """
    raise NotImplementedError("T4.2")
