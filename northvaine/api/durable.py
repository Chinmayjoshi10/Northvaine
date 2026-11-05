"""Durable app state (D144): what a visitor makes on the free server survives a restart.

The free host wipes its disk on every restart and redeploy. The disk stays the working copy (the
pages read files as before); every record a visitor creates is also written to the `app_state`
table, and `hydrate` writes the saved records back to disk when the server starts.

Kinds:
- `onboarding`: a "Build my radar" session (JSON), key = session id;
- `onboarding_text`: a session's website or catalogue text, key = `<sid>.site` or
  `<sid>.catalogue`;
- `client`: a client spec built from confirmed answers, key = client id;
- `trial`: one claimed free radar, key = `<email>|<session id>`, value = one JSON line;
- `request`: one "subscribe" or "talk to us" request, key = `<time>-<random>`;
- `report`: a file of a finished radar, key = its path under the reports folder;
- `feedback`: one feedback line, key = `<client>/<time>-<random>`;
- `cache:<run key>`: a run's saved web and model answers (radar/resume.py).

Everything here is best effort: a database error is logged and the app carries on from disk. With
no database configured (tests, local runs) every function does nothing.
"""

from __future__ import annotations

import asyncio
import logging
import zlib
from pathlib import Path

from northvaine.core.settings import get_settings

logger = logging.getLogger(__name__)

UPSERT = (
    "INSERT INTO app_state (kind, key, value) VALUES (:kind, :key, :value) "
    "ON CONFLICT (kind, key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()"
)
SELECT_ONE = "SELECT value FROM app_state WHERE kind = :kind AND key = :key"
SELECT_KIND = (
    "SELECT key, value FROM app_state WHERE kind = :kind AND key LIKE :prefix ORDER BY key"
)

_queue: asyncio.Queue[tuple[str, str, str]] | None = None
_writer: asyncio.Task[None] | None = None
_loop: asyncio.AbstractEventLoop | None = None


def enabled() -> bool:
    settings = get_settings()
    return settings.durable_state and settings.database_url is not None


def _pack(text: str) -> bytes:
    return zlib.compress(text.encode("utf-8"), 6)


def _unpack(value: bytes) -> str:
    return zlib.decompress(bytes(value)).decode("utf-8")


async def put(kind: str, key: str, text: str) -> None:
    """Save one record now (insert or replace)."""
    if not enabled():
        return
    from sqlalchemy import text as sql

    from northvaine.core.db import session_scope

    try:
        async with session_scope() as session:
            await session.execute(sql(UPSERT), {"kind": kind, "key": key, "value": _pack(text)})
    except Exception as exc:  # best effort: the disk copy is still there
        logger.warning("app_state put failed (%s/%s): %s", kind, key, type(exc).__name__)


async def get(kind: str, key: str) -> str | None:
    if not enabled():
        return None
    from sqlalchemy import text as sql

    from northvaine.core.db import session_scope

    try:
        async with session_scope() as session:
            row = (await session.execute(sql(SELECT_ONE), {"kind": kind, "key": key})).first()
    except Exception as exc:
        logger.warning("app_state get failed (%s/%s): %s", kind, key, type(exc).__name__)
        return None
    return _unpack(row[0]) if row else None


async def items(kind: str, prefix: str = "") -> list[tuple[str, str]]:
    """Every record of a kind whose key starts with `prefix`, in key order."""
    if not enabled():
        return []
    from sqlalchemy import text as sql

    from northvaine.core.db import session_scope

    pattern = prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    try:
        async with session_scope() as session:
            result = await session.execute(sql(SELECT_KIND), {"kind": kind, "prefix": pattern})
            rows = result.all()
    except Exception as exc:
        logger.warning("app_state items failed (%s): %s", kind, type(exc).__name__)
        return []
    return [(key, _unpack(value)) for key, value in rows]


def save_later(kind: str, key: str, text: str) -> None:
    """Queue a record to be saved by one background writer, in order. Safe to call from sync
    code that runs inside the event loop; without a running loop or a database it does nothing."""
    global _queue, _writer, _loop
    if not enabled():
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    if _queue is None or _loop is not loop or _writer is None or _writer.done():
        _queue = asyncio.Queue()
        _loop = loop
        _writer = loop.create_task(_drain(_queue))
    _queue.put_nowait((kind, key, text))


async def _drain(queue: asyncio.Queue[tuple[str, str, str]]) -> None:
    while True:
        kind, key, text = await queue.get()
        try:
            await put(kind, key, text)
        finally:
            queue.task_done()


async def flush() -> None:
    """Wait until every queued record is saved."""
    if _queue is not None and _loop is asyncio.get_running_loop():
        await _queue.join()


def _write_new(path: Path, text: str) -> bool:
    if path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return True


def _merge_lines(path: Path, lines: list[str]) -> None:
    have = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
    known = set(have)
    extra = [line for line in lines if line.strip() and line not in known]
    if extra:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.writelines(line + "\n" for line in extra)


def _safe(base: Path, relative: str) -> Path | None:
    """`base/relative` only when it stays inside `base`."""
    target = (base / relative).resolve()
    return target if target.is_relative_to(base.resolve()) else None


async def hydrate(reports: Path, clients: Path) -> dict[str, int]:
    """Write the saved records back to disk (at server start). Files that came with the image are
    never overwritten; line files (trials, feedback) are merged."""
    counts: dict[str, int] = {}
    if not enabled():
        return counts
    folder = reports / "_onboarding"
    for kind, target in (("onboarding", folder), ("onboarding_text", folder)):
        rows = await items(kind)
        for key, text in rows:
            path = _safe(target, f"{key}.json" if kind == "onboarding" else f"{key}.txt")
            if path is not None:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding="utf-8")
        counts[kind] = len(rows)
    rows = await items("client")
    for key, text in rows:
        path = _safe(clients, f"{key}.json")
        if path is not None:
            _write_new(path, text)
    counts["client"] = len(rows)
    rows = await items("report")
    for key, text in rows:
        path = _safe(reports, key)
        if path is not None:
            _write_new(path, text)
    counts["report"] = len(rows)
    from northvaine.api.accounts import REQUESTS, TRIALS

    for kind, name in (("trial", TRIALS), ("request", REQUESTS)):
        rows = await items(kind)
        _merge_lines(reports / name, [text for _, text in rows])
        counts[kind] = len(rows)
    rows = await items("feedback")
    by_client: dict[str, list[str]] = {}
    for key, text in rows:
        by_client.setdefault(key.split("/", 1)[0], []).append(text)
    for client, lines in by_client.items():
        path = _safe(reports.parent / "feedback", f"{client}.jsonl")
        if path is not None:
            _merge_lines(path, lines)
    counts["feedback"] = len(rows)
    return counts
