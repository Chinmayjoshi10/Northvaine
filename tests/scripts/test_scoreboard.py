"""The lead-quality scoreboard (D106). Invented companies; no network, no model."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

REPO = Path(__file__).resolve().parents[2]


def _module() -> ModuleType:
    path = REPO / "scripts" / "scoreboard.py"
    spec = importlib.util.spec_from_file_location("nv_scoreboard", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


RUN = {
    "entries": [
        {"rank": 1, "candidate": {"name": "EXAMPLE TRADING LIMITE D"}},
        {"rank": 2, "candidate": {"name": "Northwind Interiors Ltd"}},
    ],
    "rejected": [
        {"candidate": {"name": "Bluefield Supplies Inc."}, "gate": {"rejected_as": "not_a_buyer"}},
        {"candidate": {"name": "(no company named)"}, "gate": {"rejected_as": "not_a_buyer"}},
    ],
}
TARGETS = {
    "markets": ["GB", "US"],
    "targets": [
        {"name": "Example Trading Ltd", "country": "GB"},
        {"name": "Bluefield Supplies", "country": "US"},
        {"name": "Harbour Works", "country": "GB", "aliases": ["Northwind Interiors"]},
        {"name": "Far Away Builders", "country": "AU"},
        {"name": "AB", "country": "GB"},
    ],
}


def test_scores_briefed_rejected_and_missed() -> None:
    result = _module().score(RUN, TARGETS)
    status = {r["name"]: r["status"] for r in result["rows"]}
    assert status == {
        "Example Trading Ltd": "briefed",  # HMRC's split legal form still matches
        "Bluefield Supplies": "rejected",
        "Harbour Works": "briefed",  # matched on an alias
        "Far Away Builders": "missed",
        "AB": "missed",  # too short to match safely
    }
    assert (result["found"], result["total"]) == (2, 5)
    assert (result["found_in_market"], result["total_in_market"]) == (2, 4)


def test_render_states_both_scores() -> None:
    module = _module()
    text = module.render(module.score(RUN, TARGETS))
    assert text.startswith("Found 2 of 5 hand-found buyers; 2 of 4 in the client's markets.")
