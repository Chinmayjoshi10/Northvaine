"""SIMULATED learning study (D89) on a replayed recording: the loop's dynamics, labelled."""

from __future__ import annotations

from pathlib import Path

from northvaine.eval.simulate import OwnerSpec, load_owner, render_report, simulate
from tests.radar.test_radar_replay import replay

OWNERS = Path(__file__).resolve().parents[1] / "fixtures" / "owners"


def test_owner_specs_are_data_and_load() -> None:
    owners = [load_owner(p) for p in sorted(OWNERS.glob("*.json"))]
    assert len(owners) >= 3
    assert all(isinstance(o, OwnerSpec) and o.name for o in owners)


def test_learning_beats_random_on_the_same_budget_when_taste_is_learnable() -> None:
    run = replay("stone_supplier").run
    owner = load_owner(OWNERS / "tender_hunter.json")
    report = simulate(run, owner, seeds=12, rounds=10)
    last = report.rounds[-4:]
    learning = sum(r.learning for r in last) / len(last)
    baseline = sum(r.baseline for r in last) / len(last)
    assert learning > baseline
    assert report.liked_in_pool > 0


def test_the_report_says_simulated_everywhere() -> None:
    run = replay("packaging_supplier").run
    report = simulate(run, OwnerSpec(name="any"), seeds=2, rounds=3)
    text = render_report(report)
    assert text.startswith("# SIMULATED")
    header = next(line for line in text.splitlines() if line.startswith("| Round"))
    assert header.count("SIMULATED") == 3


def test_the_study_is_reproducible() -> None:
    run = replay("packaging_supplier").run
    owner = OwnerSpec(name="x", countries=["FR"])
    assert simulate(run, owner, seeds=3, rounds=4) == simulate(run, owner, seeds=3, rounds=4)
