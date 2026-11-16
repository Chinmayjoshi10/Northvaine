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
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from northvaine.api import durable, onboarding
from northvaine.api.supervisor import EXIT_DONE, EXIT_FINAL
from northvaine.brain.errors import BudgetExceeded
from northvaine.core.settings import get_settings
from northvaine.jobs.resume import ResumeCache

logger = logging.getLogger(__name__)

HEARTBEAT_SECONDS = 20.0
ACTIVITY_SECONDS = 20 * 60  # longer than any one step has taken on the free server
EXIT_RETRY = 1


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _start_heartbeat(base: Path, sid: str, last_activity: Callable[[], float]) -> threading.Event:
    """Touch the run's heartbeat file every HEARTBEAT_SECONDS from a thread of its own, so a long
    CPU-heavy step on the free server's small CPU never makes a healthy run look dead. A separate
    file, so it never races the progress updates written to the session file.

    The thread beats only while the run shows activity (a progress step, or an answer asked for
    or received) within ACTIVITY_SECONDS: a run stuck on a call that never returns goes silent,
    and the supervisor stops it after `onboarding_stale_seconds` instead of the hour limit."""
    stop = threading.Event()
    path = onboarding.heartbeat_path(base, sid)

    def beat() -> None:
        while not stop.wait(HEARTBEAT_SECONDS):
            if time.monotonic() - last_activity() > ACTIVITY_SECONDS:
                continue
            try:
                path.write_text(_now(), encoding="utf-8")
            except OSError:  # a missed beat is harmless; a dead thread is not
                logger.warning("run %s: heartbeat not written", sid)

    path.write_text(_now(), encoding="utf-8")
    threading.Thread(target=beat, name="heartbeat", daemon=True).start()
    return stop


def peak_mb() -> int | None:
    """The process's peak memory in MB (Linux; None elsewhere), logged so an out-of-memory
    notice from the host can be checked against real numbers (16 Nov)."""
    try:
        import resource

        return int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024)
    except (ImportError, OSError):
        return None


async def _drop_cache(sid: str) -> None:
    """A run that will not be tried again needs no saved answers (D146); a free database fills
    up otherwise. Pending writes go first, or they would put the rows back."""
    await durable.flush()
    await durable.drop_kind(ResumeCache(sid).kind)


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
    activity = {"at": time.monotonic(), "cache": None}

    def last_activity() -> float:
        cache = activity["cache"]
        return max(activity["at"], cache.last_activity if cache is not None else 0.0)

    beat = _start_heartbeat(base, sid, last_activity)

    def progress(stage: str) -> None:
        activity["at"] = time.monotonic()
        onboarding._update(base, sid, progress=stage, heartbeat_at=_now())

    try:
        spec = load_client_spec(session.client_id, onboarding.clients_dir())
        spec = spec.model_copy(update={"markets": spec.markets[: onboarding.QUICK_MAX_MARKETS]})
        cache = await ResumeCache.load(sid)
        activity["cache"] = cache
        if cache.saved:
            logger.info("run %s resumes with %d saved answers", sid, len(cache.saved))
        result = await run_live(spec, as_of=as_of, settings=quick, progress=progress, resume=cache)
        logger.info("run %s: %d answers replayed, %d new", sid, cache.hits, cache.misses)
        logger.info("run %s: peak memory %s MB", sid, peak_mb())
        paths = write_reports(result, base)
        del result
        gc.collect()
        for path in paths:
            await durable.put(
                "report", path.relative_to(base).as_posix(), path.read_text(encoding="utf-8")
            )
        onboarding._update(base, sid, stage="done", progress=None, last_error=None)
        await _drop_cache(sid)
        return EXIT_DONE
    except BudgetExceeded as exc:
        onboarding._update(base, sid, last_error=f"money cap reached ({exc.kind})")
        await _drop_cache(sid)
        return EXIT_FINAL
    except Exception as exc:
        logger.exception("run %s stopped", sid)
        onboarding._update(base, sid, last_error=f"{type(exc).__name__}: {exc}"[:300])
        return EXIT_RETRY
    finally:
        beat.set()
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
