"""Async database engine, sessions and health check (contract; implemented by T1.2).

Importing this module is cheap and side-effect free: no engine is built and no setting is
read until a function is called. SQLAlchemy types are imported for annotations only.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

    from northvaine.core.settings import Settings

_engine: AsyncEngine | None = None


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
    raise NotImplementedError("T1.2")


def redact_url(raw: str) -> str:
    """Return the URL with its password replaced by "***"."""
    raise NotImplementedError("T1.2")


def create_engine(url: str | None = None, *, settings: Settings | None = None) -> AsyncEngine:
    """Build a new AsyncEngine from `url` or DATABASE_URL, honouring db_pool_mode."""
    raise NotImplementedError("T1.2")


def get_engine() -> AsyncEngine:
    """Return the lazy module-level engine, creating it on first use."""
    raise NotImplementedError("T1.2")


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    """Return the sessionmaker bound to `get_engine()` (expire_on_commit=False)."""
    raise NotImplementedError("T1.2")


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """Yield a session; commit on success, roll back on error."""
    raise NotImplementedError("T1.2")
    yield  # pragma: no cover


async def get_db() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency that yields one session per request."""
    raise NotImplementedError("T1.2")
    yield  # pragma: no cover


async def dispose_engine() -> None:
    """Dispose the module engine if one exists, and forget it. No-op when none exists."""
    global _engine
    if _engine is None:
        return
    engine, _engine = _engine, None
    await engine.dispose()


async def check_database(engine: AsyncEngine | None = None) -> DatabaseStatus:
    """Connect and report the server version and the vector / pgcrypto extensions."""
    raise NotImplementedError("T1.2")


def main() -> int:
    """`python -m northvaine.core.db`: print the database status; return an exit code."""
    raise NotImplementedError("T1.2")


if __name__ == "__main__":
    raise SystemExit(main())
