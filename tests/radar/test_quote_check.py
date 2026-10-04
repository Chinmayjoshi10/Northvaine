"""radar/quote_check.py: normalization, extracted and structured quote matching (T4.2)."""

from __future__ import annotations

import time

from northvaine.core.models import ClaimStatus, QuoteMode
from northvaine.core.settings import Settings
from northvaine.radar.quote_check import find_quote, normalize_text, quote_contains

SETTINGS = Settings(_env_file=None)

PAGE = (
    "About the company\n\n"
    "Harbourside Works has supplied road materials to public authorities since 1994.\n"
    "In March 2026 the company won a framework agreement covering six regional councils.\n"
    "Contact the sales office for a datasheet."
)
SENTENCE = "In March 2026 the company won a framework agreement covering six regional councils."


def span(text: str, offset: int | None, length: int | None) -> str:
    assert offset is not None and length is not None
    return text[offset : offset + length]


# --- normalize_text ------------------------------------------------------------------------


def test_normalize_text_handles_quotes_dashes_whitespace_and_nfkc() -> None:
    raw = "  \u201cHello\u201d\u2014it\u2019s a \u2013 test\u00a0\n\n  of  \ufb01nance  "
    assert normalize_text(raw) == '"Hello"-it\'s a - test of finance'


def test_normalize_text_empty_and_whitespace_only() -> None:
    assert normalize_text("") == ""
    assert normalize_text(" \n\t ") == ""


# --- find_quote, extracted ----------------------------------------------------------------


def test_exact_match_offset_indexes_the_original_text() -> None:
    match = find_quote(PAGE, SENTENCE, settings=SETTINGS)
    assert match.found and match.method == "exact" and match.ratio == 1.0
    assert span(PAGE, match.offset, match.length) == SENTENCE


def test_rewrapped_and_requoted_quote_is_found() -> None:
    text = "He said:  \u201cWe deliver\nacross the whole region\u201d \u2013 and meant it today."
    quote = 'He said: "We deliver across the whole region" - and meant it'
    match = find_quote(text, quote, settings=SETTINGS)
    assert match.found and match.method == "exact"
    assert span(text, match.offset, match.length) == (
        "He said:  \u201cWe deliver\nacross the whole region\u201d \u2013 and meant it"
    )


def test_unicode_nfkc_and_en_dash() -> None:
    text = "Our o\ufb03ce hours run 9\u201317 on weekdays, as agreed with every customer."
    quote = "Our office hours run 9-17 on weekdays, as agreed"
    match = find_quote(text, quote, settings=SETTINGS)
    assert match.found
    assert span(text, match.offset, match.length).startswith("Our o\ufb03ce hours run 9\u201317")


def test_paraphrase_is_rejected() -> None:
    quote = "The firm obtained a regional councils framework deal in the spring of 2026."
    match = find_quote(PAGE, quote, settings=SETTINGS)
    assert not match.found and match.reason == ClaimStatus.QUOTE_NOT_FOUND


def test_quote_from_another_document_is_rejected() -> None:
    other = "Quarterly results were published on the investor page together with the slides."
    match = find_quote(PAGE, other, settings=SETTINGS)
    assert not match.found and match.reason == ClaimStatus.QUOTE_NOT_FOUND


def test_short_quote_is_too_short_after_normalization() -> None:
    match = find_quote(PAGE, "  since  1994.  ", settings=SETTINGS)
    assert not match.found and match.reason == ClaimStatus.QUOTE_TOO_SHORT
    assert not find_quote(PAGE, "", settings=SETTINGS).found


def test_minimum_length_is_a_setting() -> None:
    relaxed = Settings(_env_file=None, quote_min_chars=5)
    assert find_quote(PAGE, "since 1994.", settings=relaxed).found


FUZZ_BASE = (
    "The depot handles forty containers every week and ships them across the northern region."
)


def corrupt(text: str, positions: list[int]) -> str:
    chars = list(text)
    for p in positions:
        chars[p] = "#"
    return "".join(chars)


def fuzz_text(quote: str) -> str:
    return "Intro line about nothing in particular. " + quote + " Closing line about nothing."


def test_near_miss_just_over_threshold_is_found_fuzzily() -> None:
    quote = FUZZ_BASE + " " + FUZZ_BASE[:31]  # 120 chars
    assert len(quote) == 120
    # 6 substitutions in 120 chars -> ratio 0.95 exactly; at the limit and found
    changed = corrupt(quote, [5, 25, 45, 65, 85, 105])
    match = find_quote(fuzz_text(changed), quote, settings=SETTINGS)
    assert match.found and match.method == "fuzzy"
    assert match.ratio >= 0.95
    assert span(fuzz_text(changed), match.offset, match.length) == changed


def test_near_miss_just_under_threshold_is_rejected() -> None:
    quote = FUZZ_BASE + " " + FUZZ_BASE[:31]
    changed = corrupt(quote, [5, 20, 35, 50, 65, 80, 95])  # 7 of 120: ratio ~0.9417
    match = find_quote(fuzz_text(changed), quote, settings=SETTINGS)
    assert not match.found and match.reason == ClaimStatus.QUOTE_NOT_FOUND


def test_fuzzy_is_skipped_on_oversized_text_but_exact_still_works() -> None:
    quote = FUZZ_BASE + " " + FUZZ_BASE[:31]
    changed = corrupt(quote, [5, 45, 85])
    small = Settings(_env_file=None, extract_max_doc_chars=50)
    big = "x " * 100 + changed + " y" * 100
    assert not find_quote(big, quote, settings=small).found
    assert find_quote(big + quote, quote, settings=small).found


def test_fuzzy_search_is_fast_on_a_large_document() -> None:
    quote = FUZZ_BASE + " " + FUZZ_BASE[:31]
    filler = ("The depot ships goods across the region every week. " * 400)[:20000]
    started = time.perf_counter()
    find_quote(filler, quote, settings=SETTINGS)
    assert time.perf_counter() - started < 5


# --- find_quote, structured ---------------------------------------------------------------

RECORD = "Title: Road works\nCPV: 45233000\nBuyer country: DEU\nValue: 1 200 000 EUR"


def test_structured_whole_lines_are_found_with_line_offsets() -> None:
    for line in ("CPV: 45233000", "Buyer country: DEU", "Title: Road works"):
        match = find_quote(RECORD, line, mode=QuoteMode.STRUCTURED, settings=SETTINGS)
        assert match.found and match.method == "line"
        assert span(RECORD, match.offset, match.length) == line
        assert RECORD[match.offset - 1 : match.offset] in ("", "\n")


def test_structured_rejects_prefix_substring_and_respaced_lines() -> None:
    for bad in ("CPV: 4523", "45233000", "CPV:  45233000", "cpv: 45233000", " CPV: 45233000", ""):
        match = find_quote(RECORD, bad, mode=QuoteMode.STRUCTURED, settings=SETTINGS)
        assert not match.found, bad
        assert match.reason == ClaimStatus.QUOTE_NOT_FOUND


def test_structured_rejects_multi_line_quote() -> None:
    quote = "CPV: 45233000\nBuyer country: DEU"
    assert not find_quote(RECORD, quote, mode=QuoteMode.STRUCTURED, settings=SETTINGS).found


def test_structured_has_no_minimum_length() -> None:
    assert find_quote("A: 1\nB: 2", "B: 2", mode=QuoteMode.STRUCTURED, settings=SETTINGS).found


# --- quote_contains -----------------------------------------------------------------------


def test_quote_contains_is_normalized_and_casefolded() -> None:
    quote = "Awarded to  Harbourside\nWorks on 12 March 2026 \u2013 final"
    assert quote_contains(quote, "harbourside works")
    assert quote_contains(quote, "12 MARCH 2026 - final")
    assert not quote_contains(quote, "Harbourside Ltd")


def test_quote_contains_empty_fragment_is_false() -> None:
    assert not quote_contains("anything", "")
    assert not quote_contains("anything", "   ")
