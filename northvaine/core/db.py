"""Async database engine, sessions and health check.

Importing this module is cheap and side-effect free: no engine is built and no setting is
read until a function is called. SQLAlchemy is imported inside the functions that need it.

Hosted providers hand out libpq URLs (`postgres://...?sslmode=require&channel_binding=...`).
SQLAlchemy passes every query key to `asyncpg.connect()` as a keyword argument, so
`normalize_database_url` rewrites the scheme and moves or drops the libpq-only keys
(docs/integrations/sqlalchemy-asyncpg.md). URLs are never logged unless redacted.
"""

from __future__ import annotations

import asyncio
import logging
import os
import ssl
import sys
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from northvaine.core import settings as settings_module
from northvaine.core.settings import ConfigError

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

    from northvaine.core.settings import Settings

logger = logging.getLogger(__name__)

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None

ASYNCPG_SCHEME = "postgresql+asyncpg"
_SCHEMES = {"postgres", "postgresql", "postgresql+psycopg", ASYNCPG_SCHEME}
SSL_MODES = ("disable", "allow", "prefer", "require", "verify-ca", "verify-full")
_SSL_FILE_KEYS = ("sslrootcert", "sslcert", "sslkey")
# libpq keys that asyncpg.connect() would reject as unexpected keyword arguments.
_DROPPED_KEYS = frozenset({"channel_binding", "options", "target_session_attrs", "gssencmode"})


@dataclass(frozen=True)
class NormalizedUrl:
    """A URL ready for SQLAlchemy + asyncpg, plus the connect_args it needs."""

    url: str  # postgresql+asyncpg://..., libpq-only query keys removed
    connect_args: dict[str, Any]  # e.g. {"ssl": "require"} or {"ssl": <SSLContext>}


@dataclass(frozen=True)
class DatabaseStatus:
    """What `check_database` learned about the server."""

    server_version: str
    server_version_num: int
    has_vector: bool
    has_pgcrypto: bool


def normalize_database_url(raw: str) -> NormalizedUrl:
    """Rewrite a hosted Postgres URL for asyncpg (driver, sslmode -> ssl, libpq keys)."""
    parts = urlsplit(raw.strip())
    scheme = parts.scheme.lower()
    if scheme not in _SCHEMES:
        raise ConfigError(
            f"DATABASE_URL scheme {scheme or '(none)'!r} is not supported; "
            "use postgresql:// or postgresql+asyncpg://"
        )

    kept: list[tuple[str, str]] = []
    dropped: list[str] = []
    files: dict[str, str] = {}
    sslmode: str | None = None
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        if key == "sslmode":
            sslmode = value.lower()
        elif key in _SSL_FILE_KEYS:
            files[key] = value
        elif key in _DROPPED_KEYS:
            dropped.append(key)
        else:
            kept.append((key, value))

    if dropped:
        logger.debug("dropped libpq-only query keys asyncpg does not accept: %s",
                     ", ".join(sorted(set(dropped))))

    connect_args: dict[str, Any] = {}
    if sslmode is not None or files:
        if any(key == "ssl" for key, _ in kept):
            raise ConfigError("DATABASE_URL sets both ssl and sslmode/sslrootcert; use one")
        connect_args["ssl"] = _ssl_setting(sslmode, files)

    url = urlunsplit((ASYNCPG_SCHEME, parts.netloc, parts.path, urlencode(kept), parts.fragment))
    return NormalizedUrl(url=url, connect_args=connect_args)


def _new_ssl_context() -> ssl.SSLContext:
    """A blank client-side TLS context (a seam for tests)."""
    return ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)


def _ssl_setting(sslmode: str | None, files: dict[str, str]) -> str | ssl.SSLContext:
    """Turn libpq's sslmode + certificate keys into asyncpg's `ssl` argument."""
    if sslmode is not None and sslmode not in SSL_MODES:
        raise ConfigError(
            f"DATABASE_URL sslmode {sslmode!r} is not one of: {', '.join(SSL_MODES)}"
        )
    if sslmode == "verify-full" and "sslrootcert" not in files:
        raise ConfigError(
            "DATABASE_URL has sslmode=verify-full but no sslrootcert; set sslrootcert to the "
            "server's CA certificate file (the libpq default root.crt path is not used)"
        )
    if not files or sslmode == "disable":
        return sslmode or "prefer"

    for key, path in files.items():
        if not path or not os.path.isfile(path):
            raise ConfigError(f"DATABASE_URL {key} file not found: {path!r}")
    if "sslkey" in files and "sslcert" not in files:
        raise ConfigError("DATABASE_URL sets sslkey without sslcert")

    verify = sslmode in ("verify-ca", "verify-full")
    context = _new_ssl_context()
    context.check_hostname = sslmode == "verify-full"
    context.verify_mode = ssl.CERT_REQUIRED if verify else ssl.CERT_NONE
    try:
        if "sslrootcert" in files:
            context.load_verify_locations(cafile=files["sslrootcert"])
        if "sslcert" in files:
            context.load_cert_chain(files["sslcert"], files.get("sslkey"))
    except (ssl.SSLError, OSError) as exc:
        raise ConfigError(f"DATABASE_URL certificate files could not be loaded: {exc}") from exc
    return context


def redact_url(raw: str) -> str:
    """Return the URL with its password replaced by "***"."""
    try:
        parts = urlsplit(raw)
    except ValueError:
        return "***"
    netloc = parts.netloc
    if "@" in netloc:
        userinfo, _, hostinfo = netloc.rpartition("@")
        if ":" in userinfo:
            userinfo = userinfo.split(":", 1)[0] + ":***"
        netloc = f"{userinfo}@{hostinfo}"
    query = parts.query
    if query:
        pairs = parse_qsl(query, keep_blank_values=True)
        if any(key == "password" for key, _ in pairs):
            query = urlencode([(k, "***" if k == "password" else v) for k, v in pairs])
    return urlunsplit((parts.scheme, netloc, parts.path, query, parts.fragment))


def _is_neon_pooler(url: str) -> bool:
    """True for a Neon pooled endpoint (`ep-...-pooler.<region>.neon.tech`), always PgBouncer
    in transaction mode (docs/integrations/postgres-hosting.md, E5)."""
    host = (urlsplit(url).hostname or "").lower()
    return host.endswith(".neon.tech") and host.split(".", 1)[0].endswith("-pooler")


def _unique_statement_name() -> str:
    return f"__asyncpg_{uuid.uuid4()}__"


def create_engine(url: str | None = None, *, settings: Settings | None = None) -> AsyncEngine:
    """Build a new AsyncEngine from `url` or DATABASE_URL, honouring db_pool_mode."""
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import NullPool

    settings = settings or settings_module.get_settings()
    raw = url if url is not None else settings_module.require_database_url(settings)
    normalized = normalize_database_url(raw)
    connect_args = dict(normalized.connect_args)

    pool_mode = settings.db_pool_mode
    if pool_mode == "session" and _is_neon_pooler(normalized.url):
        logger.info("Neon pooler host: using transaction pool mode")
        pool_mode = "transaction"

    if pool_mode == "transaction":
        connect_args.update(
            statement_cache_size=0,  # asyncpg
            prepared_statement_cache_size=0,  # SQLAlchemy dialect
            prepared_statement_name_func=_unique_statement_name,
        )
        return create_async_engine(
            normalized.url, poolclass=NullPool, connect_args=connect_args, echo=settings.db_echo,
        )
    return create_async_engine(
        normalized.url,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_pre_ping=True,
        connect_args=connect_args,
        echo=settings.db_echo,
    )


def get_engine() -> AsyncEngine:
    """Return the lazy module-level engine, creating it on first use."""
    global _engine
    if _engine is None:
        _engine = create_engine()
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    """Return the sessionmaker bound to `get_engine()` (expire_on_commit=False)."""
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    global _sessionmaker
    engine = get_engine()
    if _sessionmaker is None or _sessionmaker.kw.get("bind") is not engine:
        _sessionmaker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    return _sessionmaker


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """Yield a session; commit on success, roll back on error."""
    async with get_sessionmaker()() as session:
        try:
            yield session
            await session.commit()
        except BaseException:
            await session.rollback()
            raise


async def get_db() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency that yields one session per request.

    It does not commit: the endpoint commits what it wants kept. Anything uncommitted is
    rolled back when the session closes.
    """
    async with get_sessionmaker()() as session:
        yield session


async def dispose_engine() -> None:
    """Dispose the module engine if one exists, and forget it. No-op when none exists."""
    global _engine, _sessionmaker
    if _engine is None:
        return
    engine, _engine, _sessionmaker = _engine, None, None
    await engine.dispose()


async def check_database(engine: AsyncEngine | None = None) -> DatabaseStatus:
    """Connect and report the server version and the vector / pgcrypto extensions."""
    from sqlalchemy import text

    engine = engine or get_engine()
    async with engine.connect() as conn:
        version = (await conn.execute(text("SHOW server_version"))).scalar_one()
        version_num = (await conn.execute(text("SHOW server_version_num"))).scalar_one()
        result = await conn.execute(text("SELECT extname FROM pg_extension"))
        extensions = set(result.scalars())
    return DatabaseStatus(
        server_version=str(version),
        server_version_num=int(version_num),
        has_vector="vector" in extensions,
        has_pgcrypto="pgcrypto" in extensions,
    )


def _scrub(message: str, raw: str) -> str:
    """Remove the URL's password from an error message, in case a library echoed it."""
    try:
        password = urlsplit(raw).password
    except ValueError:
        password = None
    return message.replace(password, "***") if password else message


async def _check_and_dispose() -> DatabaseStatus:
    try:
        return await check_database()
    finally:
        await dispose_engine()


def main() -> int:
    """`python -m northvaine.core.db`: print the database status; return an exit code."""
    try:
        raw = settings_module.require_database_url()
        normalize_database_url(raw)
        status = asyncio.run(_check_and_dispose())
    except ConfigError as exc:
        print(f"database config error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        message = _scrub(str(exc), raw)
        print(f"database check failed: {type(exc).__name__}: {message}", file=sys.stderr)
        return 1
    print(f"database: {redact_url(raw)}")
    print(f"server_version: {status.server_version} ({status.server_version_num})")
    print(f"vector: {'yes' if status.has_vector else 'no'}")
    print(f"pgcrypto: {'yes' if status.has_pgcrypto else 'no'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
