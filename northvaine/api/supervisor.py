"""The run supervisor (D144): radars run in their own process, one at a time, watched from here.

Why: the free server has a tenth of a CPU. A radar running inside the web process starved it, the
host's health check went unanswered and the host restarted the server, losing the run (30 Oct).
Now the web process only answers pages and watches; the radar runs in a separate, lower-priority
process (`northvaine.jobs.onboarding_run`) and reports through its session file.

Rules:
- one run at a time (memory); the others wait in the queue, oldest first;
- a run process that exits without finishing is an attempt; it is tried again up to
  `onboarding_max_attempts` times, then the session fails with a clear message;
- a run left "running" by a restart of the server is resumed (not counted as an attempt) up to
  `onboarding_max_resumes` times; its saved answers make the replay quick (radar/resume.py);
- a process that has not reported for `onboarding_stale_seconds`, or has run longer than
  `onboarding_run_timeout_seconds`, is stopped and counted as an attempt;
- exit code 3 means "stop for good" (for example the money cap): no retry.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from northvaine.api import onboarding
from northvaine.core.settings import get_settings

logger = logging.getLogger(__name__)

EXIT_DONE = 0
EXIT_FINAL = 3  # the run stopped for a reason a retry cannot fix
KEEP_AWAKE_SECONDS = 240.0

FAILED_MESSAGE = (
    "We could not finish your radar this time. Your free radar is still yours: start again with "
    "the same email, or open an example radar."
)

_wake = asyncio.Event()
_task: asyncio.Task[None] | None = None
_current: Supervisor | None = None


def wake() -> None:
    """Look at the queue now instead of at the next tick."""
    _wake.set()


def _seconds_since(stamp: str | None) -> float:
    if not stamp:
        return 0.0
    try:
        then = datetime.fromisoformat(stamp)
    except ValueError:
        return 0.0
    return (datetime.now(UTC) - then).total_seconds()


class Supervisor:
    def __init__(self, base: Path, *, tick_seconds: float = 3.0) -> None:
        self.base = base
        self.tick_seconds = tick_seconds
        self.process: asyncio.subprocess.Process | None = None
        self.sid: str | None = None
        self._last_ping = float("-inf")

    def resume_after_restart(self) -> list[str]:
        """Sessions a restart left "running" go back to the front of the queue."""
        settings = get_settings()
        resumed = []
        for session in onboarding.sessions(self.base):
            if session.stage != "running":
                continue
            if session.resumes >= settings.onboarding_max_resumes:
                onboarding._update(
                    self.base, session.id, stage="failed", error=FAILED_MESSAGE,
                    last_error="too many restarts",
                )  # fmt: skip
                continue
            onboarding._update(
                self.base,
                session.id,
                stage="queued",
                resumes=session.resumes + 1,
                progress="Picking up where it stopped",
            )
            resumed.append(session.id)
        return resumed

    async def run_forever(self) -> None:
        while True:
            try:
                await self.tick()
            except Exception:  # the supervisor must never die
                logger.exception("supervisor tick failed")
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(_wake.wait(), timeout=self.tick_seconds)
            _wake.clear()

    async def tick(self) -> None:
        if self.process is not None:
            if self.process.returncode is None:
                self._check_alive()
                await self._keep_awake()
                return
            self._finished(self.process.returncode)
        nxt = next((s for s in onboarding.queue(self.base) if s.stage == "queued"), None)
        if nxt is not None:
            await self._start(nxt.id)

    async def _keep_awake(self) -> None:
        """While a run is going, visit our own public address now and then: the free host puts a
        server to sleep after 15 minutes without visitors, which would stop a run whose visitor
        closed the page. Only while a run is going; the host sets RENDER_EXTERNAL_URL."""
        url = os.environ.get("RENDER_EXTERNAL_URL")
        now = asyncio.get_running_loop().time()
        if not url or now - self._last_ping < KEEP_AWAKE_SECONDS:
            return
        self._last_ping = now
        from northvaine.sensors.http import new_client

        try:
            async with new_client(20.0) as client:
                await client.get(url.rstrip("/") + "/health")
        except Exception:  # a missed ping is retried at the next interval
            logger.info("keep-awake ping failed")

    def _check_alive(self) -> None:
        settings = get_settings()
        assert self.sid is not None and self.process is not None
        try:
            session = onboarding._load(self.base, self.sid)
        except Exception:
            return
        silent = _seconds_since(session.heartbeat_at or session.started_at)
        running = _seconds_since(session.started_at)
        if silent > settings.onboarding_stale_seconds or (
            running > settings.onboarding_run_timeout_seconds
        ):
            logger.warning("run %s stopped: silent %.0fs, running %.0fs", self.sid, silent, running)
            self.process.kill()

    def _finished(self, code: int) -> None:
        sid, self.process, self.sid = self.sid, None, None
        if sid is None:
            return
        try:
            session = onboarding._load(self.base, sid)
        except Exception:
            return
        if session.stage == "done":
            return
        settings = get_settings()
        attempts = session.attempts + 1
        if code == EXIT_FINAL or attempts >= settings.onboarding_max_attempts:
            onboarding._update(
                self.base, sid, stage="failed", attempts=attempts, error=FAILED_MESSAGE
            )
            return
        onboarding._update(
            self.base,
            sid,
            stage="queued",
            attempts=attempts,
            progress="Trying again",
        )
        wake()

    async def _start(self, sid: str) -> None:
        settings = get_settings()
        now = datetime.now(UTC).replace(microsecond=0).isoformat()
        onboarding._update(self.base, sid, stage="running", started_at=now, heartbeat_at=now)
        nice = settings.onboarding_worker_nice

        def lower_priority() -> None:  # runs in the child before the run starts (POSIX only)
            if nice:
                os.nice(nice)

        kwargs = {"preexec_fn": lower_priority} if os.name == "posix" else {}
        self.process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "northvaine.jobs.onboarding_run",
            sid,
            **kwargs,  # type: ignore[arg-type]
        )
        self.sid = sid
        logger.info("run %s started in process %s", sid, self.process.pid)


def start(base: Path) -> Supervisor:
    """Start the supervisor in the running event loop (app startup)."""
    global _task, _current
    supervisor = _current = Supervisor(base)
    supervisor.resume_after_restart()
    _task = asyncio.get_running_loop().create_task(supervisor.run_forever())
    return supervisor


async def stop() -> None:
    """Stop the supervisor and any run process it started (the run resumes at the next start)."""
    global _task, _current
    process = _current.process if _current is not None else None
    if process is not None and process.returncode is None:
        process.kill()
    _current = None
    if _task is not None:
        _task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await _task
        _task = None
