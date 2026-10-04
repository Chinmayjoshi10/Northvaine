"""One radar run per client (T5.6): discover, extract, identify, gate, skeptic, rank."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from northvaine.brain.budget import RunContext
from northvaine.core.models import EventConceptRow
from northvaine.core.settings import Settings
from northvaine.radar.discover import PageFetcher
from northvaine.radar.models import ClientSpec, RadarRun

__all__ = ["run_radar", "seeded_concepts"]


def seeded_concepts() -> list[EventConceptRow]:
    """The level-0 event concepts seeded by migration 0002."""
    raise NotImplementedError("T5.6")


async def run_radar(
    spec: ClientSpec,
    *,
    as_of: datetime,
    http: Any,  # httpx.AsyncClient | None; httpx stays out of radar imports (rule: sensors/)
    fetcher: PageFetcher,
    concepts: list[EventConceptRow],
    run: RunContext,
    settings: Settings | None = None,
) -> RadarRun:
    """Run the whole radar pipeline for one client and return the run record (D61)."""
    raise NotImplementedError("T5.6")
