"""Rank and render (T5.5, D64): ranking, the brief and the scorecard are code.

Never imports `northvaine.brain.llm` (checked by scripts/check_invariants.py).
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from northvaine.core.settings import Settings
from northvaine.radar.models import (
    Candidate,
    GateDecision,
    RadarRun,
    RankedEntry,
    SkepticFinding,
)

__all__ = ["rank", "render_brief", "render_scorecard", "write_reports"]


def rank(
    passed: list[tuple[Candidate, GateDecision, SkepticFinding]],
    *,
    as_of: datetime,
    settings: Settings | None = None,
) -> list[RankedEntry]:
    """Lexicographic order by (evidence strength, window urgency or recency, direct buyer),
    each component explained in `rank_reasons`; no numeric score (D64)."""
    raise NotImplementedError("T5.5")


def render_brief(run: RadarRun) -> str:
    """The Markdown brief: nine questions per entry, verified claims with verbatim quotes."""
    raise NotImplementedError("T5.5")


def render_scorecard(run: RadarRun) -> str:
    """The founder's scorecard: one row per entry, four yes/no columns, failure chips."""
    raise NotImplementedError("T5.5")


def write_reports(run: RadarRun, out_dir: Path) -> list[Path]:
    """Write brief.md, scorecard.md and run.json under `out_dir`; return the paths."""
    raise NotImplementedError("T5.5")
