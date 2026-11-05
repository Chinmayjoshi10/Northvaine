"""D144: radars run in their own process, watched by the supervisor; a stopped run is tried
again, a run cut short by a restart is resumed, and the run process reports through the session.
No network, no database."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from northvaine.api import onboarding, supervisor
from northvaine.api.onboarding import Session


def _session(base: Path, sid: str, **fields: Any) -> Session:
    session = Session(
        id=sid,
        company="Example Works",
        website="example.test",
        stage=fields.pop("stage", "queued"),
        created_at="2026-11-06T10:00:00+00:00",
        client_id=fields.pop("client_id", "example_test"),
        **fields,
    )
    return onboarding._save(base, session)


@pytest.fixture
def base(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(onboarding, "reports", lambda: tmp_path)
    return tmp_path


def test_queue_is_running_first_then_oldest(base: Path) -> None:
    _session(base, "b2", queued_at="2026-11-06T10:02:00+00:00")
    _session(base, "a1", queued_at="2026-11-06T10:01:00+00:00")
    _session(base, "r0", stage="running", queued_at="2026-11-06T10:03:00+00:00")
    _session(base, "d9", stage="done")
    assert [s.id for s in onboarding.queue(base)] == ["r0", "a1", "b2"]


def test_a_stopped_run_is_tried_again_then_fails(base: Path) -> None:
    _session(base, "s1", stage="running")
    sup = supervisor.Supervisor(base)
    for attempt in (1, 2):
        sup.sid = "s1"
        sup._finished(1)
        s = onboarding._load(base, "s1")
        assert s.stage == "queued" and s.attempts == attempt
        onboarding._update(base, "s1", stage="running")
    sup.sid = "s1"
    sup._finished(1)
    s = onboarding._load(base, "s1")
    assert s.stage == "failed" and s.attempts == 3 and "example radar" in (s.error or "")


def test_a_final_stop_is_not_retried(base: Path) -> None:
    _session(base, "s1", stage="running")
    sup = supervisor.Supervisor(base)
    sup.sid = "s1"
    sup._finished(supervisor.EXIT_FINAL)
    assert onboarding._load(base, "s1").stage == "failed"


def test_a_finished_run_is_left_alone(base: Path) -> None:
    _session(base, "s1", stage="done")
    sup = supervisor.Supervisor(base)
    sup.sid = "s1"
    sup._finished(0)
    assert onboarding._load(base, "s1").stage == "done"


def test_restart_resumes_running_sessions_without_counting_a_try(base: Path) -> None:
    _session(base, "s1", stage="running", attempts=1)
    _session(base, "s2", stage="running", resumes=6)  # onboarding_max_resumes reached
    resumed = supervisor.Supervisor(base).resume_after_restart()
    assert resumed == ["s1"]
    s1 = onboarding._load(base, "s1")
    assert s1.stage == "queued" and s1.resumes == 1 and s1.attempts == 1
    assert onboarding._load(base, "s2").stage == "failed"


def test_a_silent_run_is_stopped(base: Path) -> None:
    old = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    _session(base, "s1", stage="running", started_at=old, heartbeat_at=old)
    killed: list[bool] = []

    class Proc:
        returncode = None

        def kill(self) -> None:
            killed.append(True)

    sup = supervisor.Supervisor(base)
    sup.sid, sup.process = "s1", Proc()  # type: ignore[assignment]
    sup._check_alive()
    assert killed == [True]


async def test_supervisor_runs_a_real_process_and_retries(
    base: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The real child process: its client spec is missing, so every try stops; after the allowed
    tries the session fails with a clear message (no network: it stops before any call)."""
    monkeypatch.setenv("RADAR_REPORTS_DIR", str(base))
    monkeypatch.setenv("ONBOARDING_CLIENTS_DIR", str(base / "clients"))
    monkeypatch.setenv("DURABLE_STATE", "false")
    monkeypatch.setenv("ONBOARDING_MAX_ATTEMPTS", "2")
    from northvaine.core.settings import get_settings

    get_settings.cache_clear()
    _session(base, "s1", queued_at="2026-11-06T10:00:00+00:00")
    sup = supervisor.Supervisor(base)
    for _ in range(400):
        await sup.tick()
        if onboarding._load(base, "s1").stage == "failed":
            break
        if sup.process is not None:
            await sup.process.wait()
    s = onboarding._load(base, "s1")
    assert s.stage == "failed" and s.attempts == 2
    assert s.last_error  # the child said why it stopped
    get_settings.cache_clear()


async def test_run_process_reports_progress_and_quick_settings(
    base: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from northvaine.jobs import onboarding_run
    from northvaine.radar import brief, live, models

    seen: list[Any] = []

    async def fake_run(spec: Any, *, as_of: datetime, settings: Any, progress: Any, resume: Any):
        seen.append((spec, as_of, settings, resume))
        progress("Reading your markets")
        raise RuntimeError("no network in tests")

    class Spec:
        markets = ("GB", "DE", "FR", "IT", "ES", "NL", "BE", "PL")

        def model_copy(self, update: dict[str, Any]) -> Any:
            copy = Spec()
            copy.markets = update["markets"]
            return copy

    monkeypatch.setattr(live, "run_live", fake_run)
    monkeypatch.setattr(models, "load_client_spec", lambda *_: Spec())
    monkeypatch.setattr(brief, "write_reports", lambda *_: [])
    _session(base, "s1", stage="running", as_of="2026-11-06T09:30:00+00:00")
    code = await onboarding_run.run("s1")
    assert code == onboarding_run.EXIT_RETRY
    spec, as_of, settings, resume = seen[0]
    assert len(spec.markets) == onboarding.QUICK_MAX_MARKETS
    assert as_of == datetime(2026, 11, 6, 9, 30, tzinfo=UTC)  # the queued moment, kept on retry
    for name, value in onboarding.QUICK_PROFILE.items():
        assert getattr(settings, name) == value
    assert resume is not None and resume.kind == "cache:s1"
    s = onboarding._load(base, "s1")
    assert s.progress == "Reading your markets" and "no network" in (s.last_error or "")


async def test_run_process_marks_done(base: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from northvaine.jobs import onboarding_run
    from northvaine.radar import brief, live, models

    async def fake_run(*_: Any, **__: Any) -> str:
        return "run"

    out = base / "example_test" / "2026-11-06" / "run.json"

    def write(_run: Any, _base: Path) -> list[Path]:
        out.parent.mkdir(parents=True)
        out.write_text("{}", encoding="utf-8")
        return [out]

    class Spec:
        markets = ("GB",)

        def model_copy(self, update: dict[str, Any]) -> Any:
            return self

    monkeypatch.setattr(live, "run_live", fake_run)
    monkeypatch.setattr(models, "load_client_spec", lambda *_: Spec())
    monkeypatch.setattr(brief, "write_reports", write)
    _session(base, "s1", stage="running")
    assert await onboarding_run.run("s1") == onboarding_run.EXIT_DONE
    assert onboarding._load(base, "s1").stage == "done"
