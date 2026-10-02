"""The frozen M1 contracts (factory/board/M1/PLAN.md, "Frozen contracts") exist as specified."""

from __future__ import annotations

import dataclasses
import importlib
import inspect
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
from pydantic import ValidationError

from northvaine.core import db, queue
from northvaine.core.models import EventType, Job, JobStatus, NewJob
from northvaine.core.settings import Settings

P = inspect.Parameter
POS = P.POSITIONAL_OR_KEYWORD
KW = P.KEYWORD_ONLY
NO = P.empty

# function name -> [(parameter, kind, default)]
DB_CONTRACT: dict[str, list[tuple[str, inspect._ParameterKind, object]]] = {
    "normalize_database_url": [("raw", POS, NO)],
    "redact_url": [("raw", POS, NO)],
    "create_engine": [("url", POS, None), ("settings", KW, None)],
    "get_engine": [],
    "get_sessionmaker": [],
    "session_scope": [],
    "get_db": [],
    "dispose_engine": [],
    "check_database": [("engine", POS, None)],
    "main": [],
}

QUEUE_CONTRACT: dict[str, list[tuple[str, inspect._ParameterKind, object]]] = {
    "enqueue": [("session", POS, NO), ("job", POS, NO)],
    "claim": [("session", POS, NO), ("worker_id", POS, NO), ("kinds", POS, None)],
    "heartbeat": [("session", POS, NO), ("job_id", POS, NO), ("worker_id", POS, NO)],
    "complete": [("session", POS, NO), ("job_id", POS, NO), ("worker_id", POS, NO)],
    "fail": [
        ("session", POS, NO), ("job_id", POS, NO), ("worker_id", POS, NO), ("error", POS, NO),
    ],
    "requeue_stale": [("session", POS, NO), ("lease_seconds", POS, None)],
    "backoff_delay": [("attempts", POS, NO), ("base_seconds", KW, None), ("max_seconds", KW, None)],
    "run_worker": [
        ("handlers", POS, NO), ("worker_id", POS, NO), ("once", KW, False),
        ("poll_seconds", KW, 1.0), ("sessionmaker", KW, None),
    ],
}


def params(func: object) -> list[tuple[str, inspect._ParameterKind, object]]:
    sig = inspect.signature(func)  # type: ignore[arg-type]
    return [(p.name, p.kind, p.default) for p in sig.parameters.values()]


def test_core_imports_without_database_url(tmp_path: Path) -> None:
    """Fresh interpreter, no DATABASE_URL, no .env in cwd: every core module imports."""
    code = textwrap.dedent(
        """
        import sys
        import northvaine.core, northvaine.core.db, northvaine.core.queue
        import northvaine.core.models, northvaine.core.settings
        assert "sqlalchemy.ext.asyncio" not in sys.modules, "db.py must import SQLAlchemy lazily"
        """
    )
    hidden = {"DATABASE_URL", "TEST_DATABASE_URL"}
    env = {k: v for k, v in os.environ.items() if k.upper() not in hidden}
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[2])
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=tmp_path, capture_output=True, text=True, env=env,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_core_package_has_no_settings_instance() -> None:
    core = importlib.import_module("northvaine.core")
    assert not hasattr(core, "settings") or inspect.ismodule(core.settings)
    source = Path(core.__file__).read_text(encoding="utf-8")  # type: ignore[arg-type]
    assert "Settings(" not in source
    assert "nvidia" not in source.lower()


@pytest.mark.parametrize(("name", "expected"), DB_CONTRACT.items())
def test_db_signatures(name: str, expected: list[tuple[str, object, object]]) -> None:
    assert params(getattr(db, name)) == expected


@pytest.mark.parametrize(("name", "expected"), QUEUE_CONTRACT.items())
def test_queue_signatures(name: str, expected: list[tuple[str, object, object]]) -> None:
    assert params(getattr(queue, name)) == expected


def test_async_kinds() -> None:
    for name in ("get_db", "dispose_engine", "check_database"):
        func = getattr(db, name)
        assert inspect.iscoroutinefunction(func) or inspect.isasyncgenfunction(func), name
    for name in ("enqueue", "claim", "heartbeat", "complete", "fail", "requeue_stale",
                 "run_worker"):
        assert inspect.iscoroutinefunction(getattr(queue, name)), name
    for name in ("normalize_database_url", "redact_url", "create_engine", "get_engine",
                 "get_sessionmaker", "main"):
        assert not inspect.iscoroutinefunction(getattr(db, name)), name
    assert not inspect.iscoroutinefunction(queue.backoff_delay)


def fields(cls: type) -> list[str]:
    assert dataclasses.is_dataclass(cls)
    assert cls.__dataclass_params__.frozen  # type: ignore[attr-defined]
    return [f.name for f in dataclasses.fields(cls)]


def test_dataclass_fields() -> None:
    assert fields(db.NormalizedUrl) == ["url", "connect_args"]
    assert fields(db.DatabaseStatus) == [
        "server_version", "server_version_num", "has_vector", "has_pgcrypto",
    ]
    assert fields(queue.StaleResult) == ["requeued", "failed"]


async def test_dispose_engine_is_noop_without_engine() -> None:
    assert db._engine is None
    await db.dispose_engine()
    assert db._engine is None


def test_stubs_raise_not_implemented() -> None:
    with pytest.raises(NotImplementedError):
        db.get_engine()
    with pytest.raises(NotImplementedError):
        queue.backoff_delay(1)


# --- core models ---------------------------------------------------------------------------

SPEC_EVENT_TYPES = {
    "facility_opened", "contract_awarded", "tender_published", "hiring_surge",
    "leadership_change", "product_launch", "market_entry", "trade_measure", "website_change",
    "reorder_due", "quote_stale", "inbound_question",
}


def test_event_types_match_spec() -> None:
    assert {e.value for e in EventType} == SPEC_EVENT_TYPES
    assert len(EventType) == 12
    for e in EventType:
        assert e.name.lower() == e.value


def test_job_status_values() -> None:
    assert [s.value for s in JobStatus] == ["queued", "running", "done", "failed"]


@pytest.mark.parametrize("kind", ["Discover", "1discover", "dis-cover", "", "a" * 65, "dis cover"])
def test_new_job_rejects_bad_kind(kind: str) -> None:
    with pytest.raises(ValidationError):
        NewJob(kind=kind)


def test_new_job_defaults_and_extra_fields() -> None:
    job = NewJob(kind="discover_v2")
    assert job.payload == {}
    assert job.run_after is None
    assert job.max_attempts is None
    assert job.workspace_id is None
    with pytest.raises(ValidationError):
        NewJob(kind="discover", priority=1)  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        NewJob(kind="discover", max_attempts=0)


def test_job_fields() -> None:
    assert list(Job.model_fields) == [
        "id", "kind", "payload", "status", "attempts", "max_attempts", "run_after",
        "locked_at", "locked_by", "error", "workspace_id", "created_at", "finished_at",
    ]


# --- test fixtures ------------------------------------------------------------------------


def test_test_database_url_fixture_skips_when_unset(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in Settings.model_fields:  # the subprocess must not see a developer's settings
        monkeypatch.delenv(name.upper(), raising=False)
    conftest = Path(__file__).resolve().parents[1] / "conftest.py"
    pytester.makeconftest(conftest.read_text(encoding="utf-8"))
    pytester.makeini(
        "[pytest]\nasyncio_mode = auto\nasyncio_default_fixture_loop_scope = function\n"
        "asyncio_default_test_loop_scope = function\nmarkers =\n    db: db\n"
    )
    pytester.makepyfile(
        """
        import pytest

        def test_uses_url(test_database_url):
            raise AssertionError("must not run")

        @pytest.mark.db
        def test_marked_db():
            raise AssertionError("must not run")

        def test_plain():
            pass
        """
    )
    result = pytester.runpytest_subprocess("-rs")
    result.assert_outcomes(passed=1, skipped=2)
    result.stdout.fnmatch_lines(["*db: set TEST_DATABASE_URL*"])
