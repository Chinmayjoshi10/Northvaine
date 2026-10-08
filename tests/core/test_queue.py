"""Unit tests for northvaine.core.queue (T1.7). No database, no network."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest

from northvaine.core import queue
from northvaine.core import settings as settings_module
from northvaine.core.models import Job, JobStatus
from northvaine.core.settings import Settings

pytestmark = pytest.mark.usefixtures("clean_settings")


def test_backoff_defaults_and_edges() -> None:
    assert queue.backoff_delay(0) == timedelta(seconds=30)
    assert queue.backoff_delay(1) == timedelta(seconds=30)
    assert queue.backoff_delay(2) == timedelta(seconds=60)
    assert queue.backoff_delay(3) == timedelta(seconds=120)
    assert queue.backoff_delay(10_000) == timedelta(seconds=3600)


def test_backoff_monotonic_and_capped() -> None:
    delays = [queue.backoff_delay(n, base_seconds=2, max_seconds=100) for n in range(0, 80)]
    assert delays == sorted(delays)
    assert max(delays) == timedelta(seconds=100)
    assert queue.backoff_delay(4, base_seconds=2, max_seconds=100) == timedelta(seconds=16)


def test_claim_statement_sql() -> None:
    from sqlalchemy.dialects import postgresql

    sql = str(queue._claim_statement("w1", ["discover"]).compile(dialect=postgresql.dialect()))
    assert "FOR UPDATE SKIP LOCKED" in sql
    assert "LIMIT" in sql
    assert "id = (" in sql
    assert "ANY" in sql
    assert "RETURNING" in sql
    plain = str(queue._claim_statement("w1").compile(dialect=postgresql.dialect()))
    assert "ANY" not in plain


def test_clean_error_redacts_secrets_and_truncates(monkeypatch: pytest.MonkeyPatch) -> None:
    secret = Settings(_env_file=None, **{"nebius_api_key": "hunter2-token-value"})  # type: ignore
    monkeypatch.setattr(settings_module, "get_settings", lambda: secret)
    cleaned = queue._clean_error("key hunter2-token-value twice hunter2-token-value")
    assert "hunter2-token-value" not in cleaned
    assert cleaned.count("***") == 2
    assert len(queue._clean_error("x" * 5000)) == 2000


class FakeSession:
    def __init__(self, log: list[str]) -> None:
        self.log = log

    async def __aenter__(self) -> FakeSession:
        self.log.append("open")
        return self

    async def __aexit__(self, *exc: object) -> None:
        self.log.append("close")

    async def commit(self) -> None:
        self.log.append("commit")

    async def rollback(self) -> None:
        self.log.append("rollback")


def make_job(job_id: int, kind: str) -> Job:
    from datetime import UTC, datetime

    now = datetime.now(UTC)
    return Job(
        id=job_id, kind=kind, payload={}, status=JobStatus.RUNNING, attempts=1, max_attempts=3,
        run_after=now, locked_at=now, locked_by="w", error=None, workspace_id=None,
        created_at=now, finished_at=None,
    )


@pytest.fixture
def harness(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    state: dict[str, Any] = {"log": [], "jobs": [], "done": [], "failed": []}

    async def fake_claim(session: Any, worker_id: str, kinds: Any = None) -> Job | None:
        return state["jobs"].pop(0) if state["jobs"] else None

    async def fake_complete(session: Any, job_id: int, worker_id: str) -> bool:
        state["log"].append("complete")
        state["done"].append(job_id)
        return True

    async def fake_fail(session: Any, job_id: int, worker_id: str, error: str) -> bool:
        state["log"].append("fail")
        state["failed"].append((job_id, error))
        return True

    monkeypatch.setattr(queue, "claim", fake_claim)
    monkeypatch.setattr(queue, "complete", fake_complete)
    monkeypatch.setattr(queue, "fail", fake_fail)
    state["sessionmaker"] = lambda: FakeSession(state["log"])
    return state


async def test_run_worker_completes_and_counts(harness: dict[str, Any]) -> None:
    harness["jobs"] = [make_job(1, "a"), make_job(2, "a")]
    seen: list[int] = []

    async def handler(job: Job) -> None:
        seen.append(job.id)
        harness["log"].append("handler")

    count = await queue.run_worker(
        {"a": handler}, "w", once=True, sessionmaker=harness["sessionmaker"]
    )
    assert count == 2
    assert seen == [1, 2]
    assert harness["done"] == [1, 2]
    # the handler runs between two closed transactions, never inside one
    first = harness["log"][: harness["log"].index("handler")]
    assert first.count("open") == first.count("close") == 1
    assert "commit" in first


async def test_run_worker_unknown_kind_fails(harness: dict[str, Any]) -> None:
    harness["jobs"] = [make_job(7, "mystery")]
    count = await queue.run_worker({}, "w", once=True, sessionmaker=harness["sessionmaker"])
    assert count == 1
    assert harness["failed"] == [(7, "no handler for kind 'mystery'")]


async def test_run_worker_handler_exception_fails_with_text(harness: dict[str, Any]) -> None:
    harness["jobs"] = [make_job(3, "a")]

    async def boom(job: Job) -> None:
        raise RuntimeError("it broke")

    maker = harness["sessionmaker"]
    count = await queue.run_worker({"a": boom}, "w", once=True, sessionmaker=maker)
    assert count == 1
    assert harness["failed"] == [(3, "it broke")]
    assert harness["done"] == []


async def test_run_worker_empty_queue_returns_zero(harness: dict[str, Any]) -> None:
    assert await queue.run_worker({}, "w", once=True, sessionmaker=harness["sessionmaker"]) == 0
