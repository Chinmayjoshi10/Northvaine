"""Unit tests for northvaine/core/db.py (T1.2). No database server is used."""

from __future__ import annotations

import logging
import os
import ssl
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from northvaine.core import db
from northvaine.core import settings as settings_module
from northvaine.core.settings import ConfigError, Settings

PW = "Sup3r-Pw-x9"
HOST = "ep-cool-darkness-123456.eu-west-2.aws.neon.tech"
ASYNC = "postgresql+asyncpg"

# A throwaway self-signed CA certificate (public, no key) for sslrootcert cases.
TEST_CA_PEM = """\
-----BEGIN CERTIFICATE-----
MIIBkjCCATegAwIBAgIUOz2uK5PsQq6m0aARceVSntHTjAYwCgYIKoZIzj0EAwIw
HTEbMBkGA1UEAwwSbm9ydGh2YWluZS10ZXN0LWNhMCAXDTI2MTAwMjE4MDY1OVoY
DzIxMjYwOTA4MTgwNjU5WjAdMRswGQYDVQQDDBJub3J0aHZhaW5lLXRlc3QtY2Ew
WTATBgcqhkjOPQIBBggqhkjOPQMBBwNCAASk18DZ7X7oV0FlYCYThcN0VzoabdT8
vvk4nalfUeBz4xijHCH80pGcZFfZR8AlXpbqRHVE9dv+4cmqAwvGETXFo1MwUTAd
BgNVHQ4EFgQUavH1wb0DrlxhTBizpqDd9WhN+gswHwYDVR0jBBgwFoAUavH1wb0D
rlxhTBizpqDd9WhN+gswDwYDVR0TAQH/BAUwAwEB/zAKBggqhkjOPQQDAgNJADBG
AiEAzB255yhfsrHzgs3tujZzPTj5z9Uz6feGQDKZmAFarp0CIQCF/lK7OV4XsKqK
Jg6vRn72jsoDBwX99mXLHp0l3aW3oA==
-----END CERTIFICATE-----
"""


def url(scheme: str = "postgresql", query: str = "", host: str = HOST) -> str:
    base = f"{scheme}://app_user:{PW}@{host}:5432/northvaine"
    return f"{base}?{query}" if query else base


@pytest.fixture(autouse=True)
def _no_password_in_logs(caplog: pytest.LogCaptureFixture) -> Iterator[None]:
    """Every test here captures DEBUG logs; none may contain the password."""
    caplog.set_level(logging.DEBUG)
    yield
    for record in caplog.records:
        assert PW not in record.getMessage(), record.getMessage()


@pytest.fixture
def ca_file(tmp_path: Path) -> str:
    path = tmp_path / "root.crt"
    path.write_text(TEST_CA_PEM, encoding="ascii")
    return str(path)


@pytest.fixture
async def reset_engine() -> Any:
    await db.dispose_engine()
    yield
    await db.dispose_engine()


# --- normalize_database_url ------------------------------------------------------------------


@pytest.mark.parametrize("scheme", ["postgres", "postgresql", "postgresql+psycopg", ASYNC])
def test_scheme_becomes_asyncpg(scheme: str) -> None:
    result = db.normalize_database_url(url(scheme))
    assert result.url == url(ASYNC)
    assert result.connect_args == {}


@pytest.mark.parametrize("scheme", ["mysql", "sqlite", "postgresql+psycopg2x", ""])
def test_unknown_scheme_raises(scheme: str) -> None:
    with pytest.raises(ConfigError, match="scheme"):
        db.normalize_database_url(url(scheme) if scheme else "just-a-string")


@pytest.mark.parametrize(
    "mode", ["disable", "allow", "prefer", "require", "verify-ca", "verify-full"]
)
def test_sslmode_moves_to_connect_args(mode: str, ca_file: str) -> None:
    query = f"sslmode={mode}&application_name=nv"
    if mode == "verify-full":
        # verify-full needs a root cert; it then becomes an SSLContext (tested below).
        result = db.normalize_database_url(url(query=query + f"&sslrootcert={ca_file}"))
        assert isinstance(result.connect_args["ssl"], ssl.SSLContext)
    else:
        result = db.normalize_database_url(url(query=query))
        assert result.connect_args == {"ssl": mode}
    assert result.url == url(ASYNC, "application_name=nv")
    assert "sslmode" not in result.url


def test_bad_sslmode_raises() -> None:
    with pytest.raises(ConfigError, match="sslmode"):
        db.normalize_database_url(url(query="sslmode=sometimes"))


def test_verify_full_without_rootcert_says_set_sslrootcert() -> None:
    with pytest.raises(ConfigError, match="set sslrootcert"):
        db.normalize_database_url(url(query="sslmode=verify-full"))


@pytest.mark.parametrize(
    ("mode", "verify_mode", "check_hostname"),
    [
        ("verify-full", ssl.CERT_REQUIRED, True),
        ("verify-ca", ssl.CERT_REQUIRED, False),
        ("require", ssl.CERT_NONE, False),
    ],
)
def test_sslrootcert_builds_context(
    mode: str, verify_mode: ssl.VerifyMode, check_hostname: bool, ca_file: str
) -> None:
    result = db.normalize_database_url(url(query=f"sslmode={mode}&sslrootcert={ca_file}"))
    context = result.connect_args["ssl"]
    assert isinstance(context, ssl.SSLContext)
    assert context.verify_mode == verify_mode
    assert context.check_hostname is check_hostname
    if verify_mode == ssl.CERT_REQUIRED:
        assert context.cert_store_stats()["x509_ca"] == 1  # our CA was loaded
    assert result.url == url(ASYNC)


class RecordingContext(ssl.SSLContext):
    """Records client cert loading, so no private key file is needed in the repo."""

    chains: list[tuple[str, str | None]]

    def load_cert_chain(self, certfile: Any, keyfile: Any = None, password: Any = None) -> None:
        self.chains.append((certfile, keyfile))


@pytest.fixture
def recording(monkeypatch: pytest.MonkeyPatch) -> list[RecordingContext]:
    made: list[RecordingContext] = []

    def factory() -> RecordingContext:
        context = RecordingContext(ssl.PROTOCOL_TLS_CLIENT)
        context.chains = []
        made.append(context)
        return context

    monkeypatch.setattr(db, "_new_ssl_context", factory)
    return made


def test_sslcert_and_sslkey_are_loaded(
    tmp_path: Path, ca_file: str, recording: list[RecordingContext]
) -> None:
    cert, key = tmp_path / "client.crt", tmp_path / "client.key"
    cert.write_text("cert", encoding="ascii")
    key.write_text("key", encoding="ascii")
    query = f"sslmode=verify-full&sslrootcert={ca_file}&sslcert={cert}&sslkey={key}"
    result = db.normalize_database_url(url(query=query))
    assert result.connect_args["ssl"] is recording[0]
    assert recording[0].chains == [(str(cert), str(key))]
    assert recording[0].check_hostname is True
    assert result.url == url(ASYNC)


@pytest.mark.parametrize("key", ["sslrootcert", "sslcert", "sslkey"])
def test_missing_cert_file_raises(key: str, tmp_path: Path) -> None:
    missing = tmp_path / "nope.pem"
    with pytest.raises(ConfigError, match=key):
        db.normalize_database_url(url(query=f"sslmode=require&{key}={missing}"))


def test_invalid_cert_file_raises(tmp_path: Path) -> None:
    bad = tmp_path / "bad.crt"
    bad.write_text("not a certificate", encoding="ascii")
    with pytest.raises(ConfigError, match="could not be loaded"):
        db.normalize_database_url(url(query=f"sslmode=verify-ca&sslrootcert={bad}"))


@pytest.mark.parametrize(
    "key", ["channel_binding", "options", "target_session_attrs", "gssencmode"]
)
def test_libpq_only_keys_are_dropped_with_debug_log(
    key: str, caplog: pytest.LogCaptureFixture
) -> None:
    result = db.normalize_database_url(url(query=f"{key}=x&sslmode=require"))
    assert result.url == url(ASYNC)
    assert result.connect_args == {"ssl": "require"}
    records = [r for r in caplog.records if r.name == "northvaine.core.db"]
    assert any(r.levelno == logging.DEBUG and key in r.getMessage() for r in records)
    assert all(HOST not in r.getMessage() and "postgres" not in r.getMessage() for r in records)


@pytest.mark.parametrize(
    "query",
    [
        "ssl=require",
        "ssl=true&application_name=nv",
        "prepared_statement_cache_size=0",
        "server_settings=x&command_timeout=5",
    ],
)
def test_other_keys_pass_through(query: str) -> None:
    result = db.normalize_database_url(url(query=query))
    assert result.url == url(ASYNC, query)
    assert result.connect_args == {}


def test_ssl_and_sslmode_together_raise() -> None:
    with pytest.raises(ConfigError, match="both ssl and sslmode"):
        db.normalize_database_url(url(query="ssl=require&sslmode=require"))


# --- redact_url ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (url(), f"postgresql://app_user:***@{HOST}:5432/northvaine"),
        (
            url(query="sslmode=require"),
            f"postgresql://app_user:***@{HOST}:5432/northvaine?sslmode=require",
        ),
        (f"postgresql://app_user@{HOST}/db", f"postgresql://app_user@{HOST}/db"),
        (
            f"postgresql://{HOST}/db?user=u&password={PW}",
            f"postgresql://{HOST}/db?user=u&password=%2A%2A%2A",
        ),
    ],
)
def test_redact_url(raw: str, expected: str) -> None:
    assert db.redact_url(raw) == expected
    assert PW not in db.redact_url(raw)


# --- engine ----------------------------------------------------------------------------------


def test_import_creates_no_engine() -> None:
    code = (
        "import sys, northvaine.core.db as d; "
        "assert d._engine is None; assert 'sqlalchemy.ext.asyncio' not in sys.modules"
    )
    env = {k: v for k, v in os.environ.items() if k.upper() != "DATABASE_URL"}
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, env=env, check=False
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.usefixtures("clean_settings", "reset_engine")
def test_get_engine_without_url_raises() -> None:
    with pytest.raises(ConfigError, match="DATABASE_URL"):
        db.get_engine()
    assert db._engine is None


@pytest.mark.usefixtures("clean_settings", "reset_engine")
def test_get_engine_is_lazy_singleton(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", url(query="sslmode=require"))
    settings_module.get_settings.cache_clear()
    assert db._engine is None
    first = db.get_engine()
    assert db.get_engine() is first
    assert first.url.drivername == ASYNC
    maker = db.get_sessionmaker()
    assert db.get_sessionmaker() is maker
    assert maker.kw["bind"] is first
    assert maker.kw["expire_on_commit"] is False


async def test_dispose_engine_resets_and_is_noop_when_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await db.dispose_engine()  # nothing to dispose: no error
    engine = db.create_engine(url(), settings=Settings(_env_file=None))
    monkeypatch.setattr(db, "_engine", engine)
    await db.dispose_engine()
    assert db._engine is None
    await db.dispose_engine()


class StopConnectError(Exception):
    pass


async def connect_kwargs(engine: Any) -> dict[str, Any]:
    """The kwargs asyncpg.connect() would receive, captured before any network I/O."""
    from sqlalchemy import event

    captured: dict[str, Any] = {}

    @event.listens_for(engine.sync_engine, "do_connect")
    def _capture(dialect: Any, conn_rec: Any, cargs: Any, cparams: dict[str, Any]) -> None:
        captured.update(cparams)
        raise StopConnectError

    with pytest.raises(StopConnectError):
        async with engine.connect():
            pass  # pragma: no cover
    await engine.dispose()
    return captured


def settings_for(mode: str) -> Settings:
    return Settings(_env_file=None, db_pool_mode=mode, db_pool_size=3, db_max_overflow=7)


async def test_transaction_mode_engine() -> None:
    from sqlalchemy.pool import NullPool

    engine = db.create_engine(url(query="sslmode=require"), settings=settings_for("transaction"))
    assert isinstance(engine.pool, NullPool)
    kwargs = await connect_kwargs(engine)
    assert kwargs["ssl"] == "require"
    assert kwargs["statement_cache_size"] == 0
    assert kwargs["prepared_statement_cache_size"] == 0
    names = {kwargs["prepared_statement_name_func"]() for _ in range(3)}
    assert len(names) == 3
    assert all(n.startswith("__asyncpg_") and n.endswith("__") for n in names)
    assert "sslmode" not in kwargs


async def test_session_mode_engine() -> None:
    from sqlalchemy.pool import AsyncAdaptedQueuePool

    engine = db.create_engine(url(query="sslmode=require"), settings=settings_for("session"))
    pool = engine.pool
    assert isinstance(pool, AsyncAdaptedQueuePool)
    assert pool.size() == 3
    assert pool._max_overflow == 7
    assert pool._pre_ping is True
    kwargs = await connect_kwargs(engine)
    assert kwargs["ssl"] == "require"
    assert "statement_cache_size" not in kwargs
    assert "prepared_statement_name_func" not in kwargs


async def test_neon_pooler_host_forces_transaction_mode() -> None:
    from sqlalchemy.pool import NullPool

    pooler = "ep-cool-darkness-123456-pooler.eu-west-2.aws.neon.tech"
    engine = db.create_engine(url(host=pooler), settings=settings_for("session"))
    assert isinstance(engine.pool, NullPool)
    assert (await connect_kwargs(engine))["statement_cache_size"] == 0


@pytest.mark.parametrize("host", [HOST, "db-pooler.example.com", "pooler.internal"])
async def test_no_other_host_inference(host: str) -> None:
    from sqlalchemy.pool import NullPool

    engine = db.create_engine(url(host=host), settings=settings_for("session"))
    assert not isinstance(engine.pool, NullPool)
    await engine.dispose()


def test_create_engine_without_url_raises() -> None:
    with pytest.raises(ConfigError, match="DATABASE_URL"):
        db.create_engine(settings=Settings(_env_file=None, database_url=None))


# --- sessions --------------------------------------------------------------------------------


class FakeSession:
    def __init__(self, calls: list[str]) -> None:
        self.calls = calls

    async def __aenter__(self) -> FakeSession:
        self.calls.append("open")
        return self

    async def __aexit__(self, *exc: object) -> None:
        self.calls.append("close")

    async def commit(self) -> None:
        self.calls.append("commit")

    async def rollback(self) -> None:
        self.calls.append("rollback")


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    log: list[str] = []
    monkeypatch.setattr(db, "get_sessionmaker", lambda: lambda: FakeSession(log))
    return log


async def test_session_scope_commits_on_success(calls: list[str]) -> None:
    async with db.session_scope() as session:
        assert isinstance(session, FakeSession)
    assert calls == ["open", "commit", "close"]


async def test_session_scope_rolls_back_and_reraises(calls: list[str]) -> None:
    with pytest.raises(ValueError, match="boom"):
        async with db.session_scope():
            raise ValueError("boom")
    assert calls == ["open", "rollback", "close"]


async def test_get_db_yields_a_session(calls: list[str]) -> None:
    gen = db.get_db()
    session = await gen.__anext__()
    assert isinstance(session, FakeSession)
    with pytest.raises(StopAsyncIteration):
        await gen.__anext__()
    assert calls == ["open", "close"]


# --- check_database and main -----------------------------------------------------------------


class FakeResult:
    def __init__(self, rows: list[Any]) -> None:
        self.rows = rows

    def scalar_one(self) -> Any:
        assert len(self.rows) == 1
        return self.rows[0]

    def scalars(self) -> list[Any]:
        return self.rows


class FakeConn:
    def __init__(self, seen: list[str]) -> None:
        self.seen = seen

    async def __aenter__(self) -> FakeConn:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def execute(self, statement: Any) -> FakeResult:
        sql = str(statement)
        self.seen.append(sql)
        if sql == "SHOW server_version":
            return FakeResult(["16.4"])
        if sql == "SHOW server_version_num":
            return FakeResult(["160004"])
        assert "pg_extension" in sql
        return FakeResult(["plpgsql", "vector"])


class FakeEngine:
    def __init__(self) -> None:
        self.seen: list[str] = []

    def connect(self) -> FakeConn:
        return FakeConn(self.seen)


async def test_check_database_reads_versions_and_extensions() -> None:
    engine = FakeEngine()
    status = await db.check_database(engine)  # type: ignore[arg-type]
    assert status == db.DatabaseStatus("16.4", 160004, has_vector=True, has_pgcrypto=False)
    assert engine.seen[:2] == ["SHOW server_version", "SHOW server_version_num"]


@pytest.mark.usefixtures("clean_settings")
def test_main_without_url_returns_1(capsys: pytest.CaptureFixture[str]) -> None:
    assert db.main() == 1
    err = capsys.readouterr().err
    assert "database config error" in err
    assert "DATABASE_URL is not set" in err
    assert "Traceback" not in err


@pytest.mark.usefixtures("clean_settings")
def test_main_prints_redacted_status(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("DATABASE_URL", url(query="sslmode=require"))

    async def fake_check(engine: Any = None) -> db.DatabaseStatus:
        return db.DatabaseStatus("16.4", 160004, has_vector=True, has_pgcrypto=True)

    monkeypatch.setattr(db, "check_database", fake_check)
    assert db.main() == 0
    out = capsys.readouterr().out
    assert PW not in out
    assert f"app_user:***@{HOST}" in out
    assert "160004" in out
    assert "vector: yes" in out


@pytest.mark.usefixtures("clean_settings")
def test_main_scrubs_password_from_errors(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("DATABASE_URL", url())

    async def failing_check(engine: Any = None) -> db.DatabaseStatus:
        raise OSError(f"cannot reach {url()}")

    monkeypatch.setattr(db, "check_database", failing_check)
    assert db.main() == 1
    err = capsys.readouterr().err
    assert "database check failed: OSError" in err
    assert PW not in err


def test_module_entry_point_calls_main(tmp_path: Path) -> None:
    env = {k: v for k, v in os.environ.items() if k.upper() != "DATABASE_URL"}
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[2])
    result = subprocess.run(
        [sys.executable, "-m", "northvaine.core.db"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert result.returncode == 1
    assert "DATABASE_URL is not set" in result.stderr
