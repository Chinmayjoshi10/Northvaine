"""T5.7: the radar's known-answer counts on the real recordings, as ranges.

`radar_expectations.json` holds, per client, the range each count of the replayed run must fall in
(documents, leads, upgraded pages, candidates, rejections by reason, entries, model calls, cost).
They are ranges, not exact numbers: a re-record legitimately moves them, and a move outside the
range is the signal to look at the new brief by eye before widening it. Run with `tasks.py golden`.

The summary test prints one table row per client for the M5 report (use `-s` to see it).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from tests.radar.test_radar_replay import CLIENTS, replay

pytestmark = pytest.mark.golden

EXPECTED: dict[str, Any] = json.loads(
    Path(__file__).with_name("radar_expectations.json").read_text(encoding="utf-8")
)


def counts(client: str) -> dict[str, Any]:
    run = replay(client).run
    reasons: dict[str, int] = {}
    for rejection in run.rejected:
        why = rejection.gate.rejected_as.value if rejection.gate.rejected_as else "none"
        reasons[why] = reasons.get(why, 0) + 1
    return {
        "documents": sum(run.documents_by_kind.values()),
        "leads": run.leads,
        "upgraded": sum(1 for p in run.upgraded if p.refused is None),
        "candidates": len(run.entries) + len(run.rejected),
        "rejected_by_reason": reasons,
        "entries": len(run.entries),
        "llm_calls": run.llm_calls,
        "cost_usd": float(run.cost_usd),
        "streams": sorted({e.candidate.stream.value for e in run.entries}),
    }


def within(name: str, value: int, bounds: list[int]) -> str | None:
    low, high = bounds
    return None if low <= value <= high else f"{name} {value} outside [{low}, {high}]"


def disagreements(client: str) -> list[str]:
    want, got = EXPECTED[client], counts(client)
    found = [
        problem
        for name in ("documents", "leads", "upgraded", "candidates", "entries", "llm_calls")
        if (problem := within(name, got[name], want[name])) is not None
    ]
    for reason, bounds in want["rejected_by_reason"].items():
        have = got["rejected_by_reason"].get(reason, 0)
        if problem := within(f"rejected as {reason}", have, bounds):
            found.append(problem)
    unexpected = set(got["rejected_by_reason"]) - set(want["rejected_reasons_allowed"])
    if unexpected:
        found.append(f"unexpected rejection reasons {sorted(unexpected)}")
    if not set(want["streams_present"]) <= set(got["streams"]):
        found.append(f"streams {got['streams']} lack some of {want['streams_present']}")
    if got["cost_usd"] > want["max_cost_usd"]:
        found.append(f"cost ${got['cost_usd']:.4f} above ${want['max_cost_usd']}")
    return found


def test_the_expectations_cover_exactly_the_sample_clients() -> None:
    assert sorted(k for k in EXPECTED if not k.startswith("_")) == sorted(CLIENTS)


@pytest.mark.parametrize("client", CLIENTS)
def test_counts_match_the_expected_ranges(client: str) -> None:
    assert not disagreements(client)


def test_summary_table_for_the_m5_report() -> None:
    header = (
        f"{'client':<20} {'docs':>5} {'leads':>5} {'upgr':>4} {'cand':>4} {'brief':>5} "
        f"{'calls':>5} {'cost':>8}  rejected by reason"
    )
    lines = [header]
    problems: dict[str, list[str]] = {}
    for client in CLIENTS:
        c = counts(client)
        reasons = ", ".join(f"{k} {v}" for k, v in sorted(c["rejected_by_reason"].items()))
        lines.append(
            f"{client:<20} {c['documents']:>5} {c['leads']:>5} {c['upgraded']:>4} "
            f"{c['candidates']:>4} {c['entries']:>5} {c['llm_calls']:>5} "
            f"${c['cost_usd']:>7.4f}  {reasons or 'none'}"
        )
        if found := disagreements(client):
            problems[client] = found
    print("\n" + "\n".join(lines))
    assert not problems, problems
