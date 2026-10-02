"""Alembic environment for Northvaine (async SQLAlchemy 2 + asyncpg).

Offline (`alembic upgrade head --sql`): renders PostgreSQL SQL with no URL, no connection and
no settings read.

Online: the URL comes from `-x url=...`, else `config.attributes["url"]`, else DATABASE_URL.
It is normalized for asyncpg by `northvaine.core.db.normalize_database_url`, and the
migrations run on a NullPool async engine inside `asyncio.run`. Call `alembic.command.*`
from sync code only (no running event loop).
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = None


def run_migrations_offline() -> None:
    """Write the migration SQL to the output buffer; no database is involved."""
    context.configure(
        dialect_name="postgresql",
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def _raw_url() -> str:
    url = context.get_x_argument(as_dictionary=True).get("url") or config.attributes.get("url")
    if url:
        return str(url)
    from northvaine.core.settings import require_database_url

    return require_database_url()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    from northvaine.core.db import normalize_database_url

    normalized = normalize_database_url(_raw_url())
    connectable = async_engine_from_config(
        {"sqlalchemy.url": normalized.url},
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        connect_args=normalized.connect_args,
    )
    try:
        async with connectable.connect() as connection:
            await connection.run_sync(do_run_migrations)
    finally:
        await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
