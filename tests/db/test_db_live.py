"""Live checks against TEST_DATABASE_URL (T1.2). Marked `db`; skipped when it is not set."""

from __future__ import annotations

import asyncio
import logging

import pytest

from northvaine.core import db

pytestmark = pytest.mark.db

logger = logging.getLogger(__name__)


async def test_check_database_reports_version_and_vector(test_database_url: str) -> None:
    from sqlalchemy import text

    logger.info("event loop: %s", type(asyncio.get_running_loop()).__name__)
    engine = db.create_engine(test_database_url)
    try:
        async with engine.begin() as conn:
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        status = await db.check_database(engine)
    finally:
        await engine.dispose()

    logger.info("server %s, pgcrypto installed: %s", status.server_version, status.has_pgcrypto)
    assert status.server_version_num >= 150000
    assert status.has_vector
    assert isinstance(status.has_pgcrypto, bool)  # information only
