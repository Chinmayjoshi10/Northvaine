"""A live radar run for the app (D105): the same pipeline as `scripts/radar.py --record`, without
recording. Model calls write `llm_calls` rows and are held to the run, daily and lifetime caps."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager, nullcontext
from datetime import datetime
from typing import Any

from northvaine.brain.budget import RunContext
from northvaine.core.settings import Settings
from northvaine.radar.discover import LivePageFetcher
from northvaine.radar.models import ClientSpec, RadarRun
from northvaine.radar.run import run_radar, seeded_concepts
from northvaine.sensors.http import new_client

__all__ = ["run_live"]


async def run_live(
    spec: ClientSpec,
    *,
    as_of: datetime,
    settings: Settings,
    progress: Callable[[str], None] | None = None,
    resume: Any = None,  # jobs.resume.ResumeCache: saved answers of an earlier try (D144)
) -> RadarRun:
    from northvaine.api import store
    from northvaine.core.db import session_scope

    seeds = store.approved_leads(store.reports_dir(), spec.id)  # D109
    fetcher: Any = LivePageFetcher(settings=settings)
    client = new_client(60.0)
    replies: AbstractContextManager[None] = nullcontext()
    if resume is not None:
        fetcher = resume.fetcher(fetcher)
        client = resume.http_client(60.0)
        replies = resume.llm()

    async with client, session_scope() as session:
        with replies:
            return await run_radar(
                spec,
                as_of=as_of,
                http=client,
                fetcher=fetcher,
                concepts=seeded_concepts(),
                run=RunContext(commit_each_call=True),
                settings=settings,
                session=session,
                seeds=seeds,
                progress=progress,
            )
