"""Quote check: find a claim's `source_quote` inside `documents.text` (T4.2, D48).

Runs in code before any LLM check (CLAUDE.md #2). Two modes: `extracted` (normalized exact match,
then a stdlib `difflib` window at `quote_match_min_ratio`, minimum `quote_min_chars`) for LLM
drafts, and `structured` (the quote must equal one whole line of the text, no normalization, no
fuzzy, no minimum) for structured records. `QuoteMatch.offset` indexes the ORIGINAL text.
"""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

from northvaine.core.models import ClaimStatus, QuoteMatch, QuoteMode
from northvaine.core.settings import Settings, get_settings

__all__ = ["find_quote", "normalize_text", "quote_contains"]

_QUOTES = str.maketrans(
    {
        "\u2018": "'",  # curly single quotes and primes
        "\u2019": "'",
        "\u201a": "'",
        "\u201b": "'",
        "\u2032": "'",
        "\u201c": '"',  # curly double quotes and primes
        "\u201d": '"',
        "\u201e": '"',
        "\u201f": '"',
        "\u2033": '"',
    }
)
# hyphen, non-breaking hyphen, figure dash, en dash, em dash, horizontal bar, minus sign, and
# the small and fullwidth hyphens
_DASHES = dict.fromkeys("\u2010\u2011\u2012\u2013\u2014\u2015\u2212\ufe58\ufe63\uff0d\u2043", "-")

# Fuzzy search is skipped on text longer than this many times `extract_max_doc_chars`.
_FUZZY_TEXT_FACTOR = 2
_FUZZY_SLACK = 0.10
_FUZZY_MAX_CANDIDATES = 12
_NUMBERS = re.compile(r"\d+(?:[.,]\d+)*")


def _units(text: str) -> list[tuple[int, int, str]]:
    """Split `text` into (start, end, normalized) units: a base character plus its combining
    marks, so NFKC composes them the way it would on the whole string."""
    units: list[tuple[int, int, str]] = []
    start = 0
    n = len(text)
    while start < n:
        end = start + 1
        while end < n and unicodedata.combining(text[end]):
            end += 1
        piece = unicodedata.normalize("NFKC", text[start:end]).translate(_QUOTES)
        piece = "".join(_DASHES.get(c, c) for c in piece)
        units.append((start, end, piece))
        start = end
    return units


def _normalize_with_map(text: str) -> tuple[str, list[int], list[int]]:
    """The normalized text plus, per normalized character, its original start and end index."""
    chars: list[str] = []
    starts: list[int] = []
    ends: list[int] = []
    for start, end, piece in _units(text):
        for ch in piece:
            if ch.isspace():
                if chars and chars[-1] == " ":
                    ends[-1] = end  # the run of whitespace spans on
                    continue
                chars.append(" ")
            else:
                chars.append(ch)
            starts.append(start)
            ends.append(end)
    # strip
    lead = 0
    while lead < len(chars) and chars[lead] == " ":
        lead += 1
    stop = len(chars)
    while stop > lead and chars[stop - 1] == " ":
        stop -= 1
    return "".join(chars[lead:stop]), starts[lead:stop], ends[lead:stop]


def normalize_text(text: str) -> str:
    """NFKC, curly quotes to straight, dashes to a hyphen, runs of whitespace to one space."""
    return _normalize_with_map(text)[0]


def _miss(reason: ClaimStatus, ratio: float = 0.0) -> QuoteMatch:
    return QuoteMatch(found=False, ratio=ratio, reason=reason)


def _find_structured(text: str, quote: str) -> QuoteMatch:
    if not quote or "\n" in quote:
        return _miss(ClaimStatus.QUOTE_NOT_FOUND)
    offset = 0
    for line in text.split("\n"):
        candidate = line[:-1] if line.endswith("\r") else line
        if candidate == quote:
            return QuoteMatch(
                found=True, offset=offset, length=len(quote), ratio=1.0, method="line"
            )
        offset += len(line) + 1
    return _miss(ClaimStatus.QUOTE_NOT_FOUND)


def _candidate_starts(norm_text: str, norm_quote: str) -> list[int]:
    """Estimated window starts, best first: where many short pieces of the quote agree.

    Every k-gram of the quote found in the text votes for the window start it implies; votes
    are pooled into buckets of the fuzzy slack. A true near-copy gathers most of its k-grams in
    one bucket, while text that merely shares common words scatters its votes, so only the few
    best-voted buckets are checked with the (quadratic) `SequenceMatcher` (D145).
    """
    k = max(4, min(8, len(norm_quote) // 4))
    grams: dict[str, list[int]] = {}
    for i in range(len(norm_quote) - k + 1):
        grams.setdefault(norm_quote[i : i + k], []).append(i)
    bucket = max(1, int(len(norm_quote) * _FUZZY_SLACK))
    exact: dict[int, int] = {}  # window start -> votes
    votes: dict[int, int] = {}  # bucket -> votes
    best_in: dict[int, int] = {}  # bucket -> its most-voted window start
    for pos in range(len(norm_text) - k + 1):
        offsets = grams.get(norm_text[pos : pos + k])
        if offsets:
            for q in offsets:
                est = pos - q
                b = est // bucket
                n = exact[est] = exact.get(est, 0) + 1
                votes[b] = votes.get(b, 0) + 1
                if n > exact.get(best_in.get(b, est), 0) or b not in best_in:
                    best_in[b] = est
    if not votes:
        return []
    # a bucket's votes plus its neighbours', since a near-copy can straddle a bucket edge; the
    # window starts where the most pieces agree exactly (intact pieces of a near-copy all do)
    pooled = {b: votes[b] + votes.get(b - 1, 0) + votes.get(b + 1, 0) for b in votes}
    ranked = sorted(pooled, key=lambda b: (-pooled[b], b))
    starts: list[int] = []
    for b in ranked:
        near = [best_in[n] for n in (b - 1, b, b + 1) if n in best_in]
        est = max(near, key=lambda e: (exact[e], -e))
        if est not in starts:
            starts.append(est)
        if len(starts) == _FUZZY_MAX_CANDIDATES:
            break
    return starts


def _find_fuzzy(norm_text: str, norm_quote: str, min_ratio: float) -> tuple[int, int, float] | None:
    """Best (start, end, ratio) over bounded windows of about the quote's length, or None."""
    length = len(norm_quote)
    slack = max(1, int(length * _FUZZY_SLACK))
    best: tuple[int, int, float] | None = None
    seen: set[tuple[int, int]] = set()
    for est in _candidate_starts(norm_text, norm_quote):
        lo = max(0, est - slack)
        hi = min(len(norm_text), est + length + slack)
        if (lo, hi) in seen or hi <= lo:
            continue
        seen.add((lo, hi))
        window = norm_text[lo:hi]
        blocks = SequenceMatcher(None, norm_quote, window, autojunk=False).get_matching_blocks()
        real = [b for b in blocks if b.size]
        if not real:
            continue
        span_start = lo + real[0].b
        span_end = lo + real[-1].b + real[-1].size
        # In text that shares the quote's words, stray matches at the window's edges stretch
        # the block span; also score the voted start itself (D145).
        spans = {
            (span_start, span_end),
            (max(span_start, est), span_end),
            (est, min(len(norm_text), est + length)),
        }
        for first, last in spans:
            if last <= first:
                continue
            matcher = SequenceMatcher(None, norm_quote, norm_text[first:last], autojunk=False)
            floor = min_ratio if best is None else max(min_ratio, best[2])
            if matcher.quick_ratio() < floor:  # a cheap upper bound on ratio()
                continue
            ratio = matcher.ratio()
            if best is None or ratio > best[2]:
                best = (first, last, ratio)
    if best is not None and best[2] >= min_ratio:
        # A near-copy may differ in wording, never in a number ("250 staff" vs "240 staff").
        if _NUMBERS.findall(norm_quote) != _NUMBERS.findall(norm_text[best[0] : best[1]]):
            return None
        return best
    return None


def find_quote(
    text: str,
    quote: str,
    *,
    mode: QuoteMode = QuoteMode.EXTRACTED,
    settings: Settings | None = None,
) -> QuoteMatch:
    """Locate `quote` in `text`; a miss carries `reason` (`quote_not_found`, `quote_too_short`)."""
    settings = settings or get_settings()
    if mode == QuoteMode.STRUCTURED:
        return _find_structured(text, quote)

    norm_quote = normalize_text(quote)
    if len(norm_quote) < settings.quote_min_chars:
        return _miss(ClaimStatus.QUOTE_TOO_SHORT)

    norm_text, starts, ends = _normalize_with_map(text)
    idx = norm_text.find(norm_quote)
    if idx >= 0:
        offset = starts[idx]
        return QuoteMatch(
            found=True,
            offset=offset,
            length=ends[idx + len(norm_quote) - 1] - offset,
            ratio=1.0,
            method="exact",
        )

    if len(norm_text) > settings.extract_max_doc_chars * _FUZZY_TEXT_FACTOR:
        return _miss(ClaimStatus.QUOTE_NOT_FOUND)
    hit = _find_fuzzy(norm_text, norm_quote, settings.quote_match_min_ratio)
    if hit is None:
        return _miss(ClaimStatus.QUOTE_NOT_FOUND)
    first, last, ratio = hit
    offset = starts[first]
    return QuoteMatch(
        found=True, offset=offset, length=ends[last - 1] - offset, ratio=ratio, method="fuzzy"
    )


def quote_contains(quote: str, fragment: str) -> bool:
    """True when `fragment` is a substring of `quote` after `normalize_text` and case folding.

    Used to ground event fields (date, subject, country, slots) in a verified quote (D50).
    """
    needle = normalize_text(fragment).casefold()
    if not needle:
        return False
    return needle in normalize_text(quote).casefold()
