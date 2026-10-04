"""T4.6: known-answer cases for the quote check (`radar.quote_check.find_quote`).

`quote_check.json` holds the cases (both modes). Each states the text, the quote and the expected
answer: found or not, how (exact, fuzzy, line), the exact slice of the ORIGINAL text that must sit
at `offset .. offset+length`, and the reason for a miss. Run with `tasks.py golden`: the summary
test prints precision, recall and every failure.

A case marked `known_gap` records an answer the implementation does not give yet; it is a strict
xfail, so fixing the code turns it into a visible failure to un-mark.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from northvaine.core.models import QuoteMode
from northvaine.radar.quote_check import find_quote

pytestmark = pytest.mark.golden

GOLDEN = Path(__file__).with_name("quote_check.json")
CASES: list[dict[str, Any]] = json.loads(GOLDEN.read_text(encoding="utf-8"))["cases"]
GAP_REASON = "known gap: {note}"


def disagreement(case: dict[str, Any]) -> str | None:
    """None when find_quote gives the expected answer, else a one-line description."""
    expect = case["expect"]
    match = find_quote(case["text"], case["quote"], mode=QuoteMode(case["mode"]))
    if match.found != expect["found"]:
        return f"expected found={expect['found']}, got found={match.found} ({match.method})"
    if not match.found:
        got = match.reason.value if match.reason else None
        if got != expect["reason"]:
            return f"expected reason {expect['reason']}, got {got}"
        return None
    if match.method != expect["method"]:
        return f"expected method {expect['method']}, got {match.method}"
    text, matched = case["text"], expect["matched"]
    if match.offset is None or match.length is None:
        return "found without an offset or a length"
    if expect["method"] == "fuzzy":
        # a fuzzy span may stop at its last matching character; the start must be exact
        if match.offset != text.index(matched):
            return f"expected offset {text.index(matched)}, got {match.offset}"
        return None
    got = text[match.offset : match.offset + match.length]
    if got != matched:
        return f"expected the slice {matched!r} at the offset, got {got!r}"
    if match.offset != text.index(matched):
        return f"expected the first occurrence at {text.index(matched)}, got {match.offset}"
    return None


def params() -> list[Any]:
    out = []
    for case in CASES:
        marks = (
            [pytest.mark.xfail(strict=True, reason=GAP_REASON.format(note=case["note"]))]
            if case.get("known_gap")
            else []
        )
        out.append(pytest.param(case, id=case["id"], marks=marks))
    return out


def test_the_set_is_big_enough_and_covers_both_modes() -> None:
    ids = [c["id"] for c in CASES]
    assert len(ids) == len(set(ids)), "case ids must be unique"
    assert len(CASES) >= 25
    for mode in QuoteMode:
        assert sum(1 for c in CASES if c["mode"] == mode.value) >= 10, mode
    # the categories the ticket names are all present
    wanted = (
        "rewrapped",
        "curly",
        "dash",
        "paraphrase",
        "near_miss_094",
        "near_miss_096",
        "short",
        "another_document",
        "whole_line",
        "prefix",
        "substring",
        "respaced",
    )
    for word in wanted:
        assert any(word in i for i in ids), f"no case for {word}"
    assert any(not c["expect"]["found"] for c in CASES)
    assert any(c["expect"]["found"] for c in CASES)


@pytest.mark.parametrize("case", params())
def test_known_answer(case: dict[str, Any]) -> None:
    problem = disagreement(case)
    assert problem is None, f"{case['id']}: {problem}"


def test_precision_and_failures(capsys: pytest.CaptureFixture[str]) -> None:
    """Precision is the share of quotes the check accepted that it should have accepted;
    recall is the share of good quotes it accepted. Both are printed; precision must be 1."""
    accepted = correct = wanted = hit = 0
    failures: list[str] = []
    gaps: list[str] = []
    for case in CASES:
        match = find_quote(case["text"], case["quote"], mode=QuoteMode(case["mode"]))
        should = case["expect"]["found"]
        problem = disagreement(case)
        if case.get("known_gap"):
            gaps.append(f"{case['id']}: {case['note']}")
            continue
        accepted += match.found
        correct += match.found and should
        wanted += should
        hit += match.found and should
        if problem:
            failures.append(f"{case['id']}: {problem}")
    precision = correct / accepted if accepted else 1.0
    recall = hit / wanted if wanted else 1.0
    with capsys.disabled():
        print(
            f"\nquote-check golden: {len(CASES) - len(gaps)} cases, precision={precision:.3f} "
            f"({correct}/{accepted} accepted quotes were right), recall={recall:.3f} "
            f"({hit}/{wanted}), failures={len(failures)}, known gaps={len(gaps)}"
        )
        for line in failures:
            print(f"  FAIL {line}")
        for line in gaps:
            print(f"  GAP  {line}")
    assert precision == 1.0
    assert not failures
