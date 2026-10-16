"""A live radar run for the app (D105): the same pipeline as `scripts/radar.py --record`, without
recording. Model calls write `llm_calls` rows and are held to the run, daily and lifetime caps."""

from __future__ import annotations

from datetime import datetime

from northvaine.brain.budget import RunContext
from northvaine.core.settings import Settings
from northvaine.radar.discover import LivePageFetcher
from northvaine.radar.models import ClientSpec, RadarRun
from northvaine.radar.run import run_radar, seeded_concepts

__all__ = ["run_live"]


async def run_live(spec: ClientSpec, *, as_of: datetime, settings: Settings) -> RadarRun:
    import httpx  # lazy: importing the radar needs no network library

    from northvaine.core.db import session_scope

    async with (
        httpx.AsyncClient(timeout=60.0) as client,
        session_scope() as session,
    ):
        return await run_radar(
            spec,
            as_of=as_of,
            http=client,
            fetcher=LivePageFetcher(settings=settings),
            concepts=seeded_concepts(),
            run=RunContext(),
            settings=settings,
            session=session,
        )
