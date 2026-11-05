"""One "Build my radar" run, in its own process (D144). Started and watched by api/supervisor.py.

    python -m northvaine.jobs.onboarding_run <session id>

It reports through the session file: the stage it is in (`progress`) and a heartbeat every
`HEARTBEAT_SECONDS`. When the radar is written, its files are saved in the durable store and the
session is marked done. Exit codes: 0 done, 1 stopped (the supervisor may try again), 3 stopped for
a reason a retry cannot fix (the money cap).
"""

from __future__ import annotations

import asyncio
import gc
import logging
import sys
from datetime import UTC, datetime

from northvaine.api import durable, onboarding
from northvaine.api.supervisor import EXIT_DONE, EXIT_FINAL
from northvaine.brain.errors import BudgetExceeded
from northvaine.core.settings import get_settings
from northvaine.jobs.resume import ResumeCache

logger = logging.getLogger(__name__)

HEARTBEAT_SECONDS = 20.0
EXIT_RETRY = 1


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


async def _heartbeat(base: object, sid: str) -> None:
    while True:
        await asyncio.sleep(HEARTBEAT_SECONDS)
        onboarding._update(base, sid, heartbeat_at=_now())  # type: ignore[arg-type]


async def run(sid: str) -> int:
    from northvaine.core.db import dispose_engine
    from northvaine.radar.brief import write_reports
    from northvaine.radar.live import run_live
    from northvaine.radar.models import load_client_spec

    base = onboarding.reports()
    session = onboarding._load(base, sid)
    if session.client_id is None:
        onboarding._update(base, sid, last_error="no client spec")
        return EXIT_FINAL
    settings = get_settings()
    quick = settings.model_copy(update=onboarding.QUICK_PROFILE)
    as_of = datetime.fromisoformat(session.as_of) if session.as_of else datetime.now(UTC)
    beat = asyncio.create_task(_heartbeat(base, sid))

    def progress(stage: str) -> None:
        onboarding._update(base, sid, progress=stage, heartbeat_at=_now())

    try:
        spec = load_client_spec(session.client_id, onboarding.clients_dir())
        spec = spec.model_copy(update={"markets": spec.markets[: onboarding.QUICK_MAX_MARKETS]})
        cache = await ResumeCache.load(sid)
        if cache.saved:
            logger.info("run %s resumes with %d saved answers", sid, len(cache.saved))
        result = await run_live(spec, as_of=as_of, settings=quick, progress=progress, resume=cache)
        logger.info("run %s: %d answers replayed, %d new", sid, cache.hits, cache.misses)
        paths = write_reports(result, base)
        del result
        gc.collect()
        for path in paths:
            await durable.put(
                "report", path.relative_to(base).as_posix(), path.read_text(encoding="utf-8")
            )
        onboarding._update(base, sid, stage="done", progress=None, last_error=None)
        return EXIT_DONE
    except BudgetExceeded as exc:
        onboarding._update(base, sid, last_error=f"money cap reached ({exc.kind})")
        return EXIT_FINAL
    except Exception as exc:
        logger.exception("run %s stopped", sid)
        onboarding._update(base, sid, last_error=f"{type(exc).__name__}: {exc}"[:300])
        return EXIT_RETRY
    finally:
        beat.cancel()
        await durable.flush()
        await dispose_engine()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s run: %(message)s")
    if len(sys.argv) != 2:
        print("usage: python -m northvaine.jobs.onboarding_run <session id>", file=sys.stderr)
        return 2
    return asyncio.run(run(sys.argv[1]))


if __name__ == "__main__":
    sys.exit(main())
