"""Live document store checks (T3.3). Marked `db`."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from northvaine.core import db
from northvaine.core.documents import (
    assert_available,
    documents_available_as_of,
    ensure_source,
    save_documents,
)
from northvaine.core.models import SourceTier
from northvaine.sensors.base import DateFlag, SensorDocument

pytestmark = pytest.mark.db

T0 = datetime(2026, 3, 1, tzinfo=UTC)


@pytest_asyncio.fixture
async def maker(migrated_url: str) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine: AsyncEngine = db.create_engine(migrated_url)
    try:
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()


def doc(
    url: str, available_at: datetime | None, *, source: str = "web", group_key: str | None = None
) -> SensorDocument:
    return SensorDocument(
        source=source,
        tier=SourceTier.COMPANY,
        url=url,
        title="T",
        text="body " + url,
        content_hash=url,
        language="en",
        published_on=date(2026, 1, 1),
        fetched_at=T0 + timedelta(days=30),
        available_at=available_at,
        external_id="e1",
        group_key=group_key,
        meta={"when": date(2026, 1, 2)},
        date_flags=[DateFlag.MISSING_PUBLICATION],
    )


async def test_ensure_source_is_idempotent(maker: async_sessionmaker[AsyncSession]) -> None:
    async with maker() as s:
        a = await ensure_source(s, "ted", SourceTier.OFFICIAL)
        b = await ensure_source(s, "ted", SourceTier.OFFICIAL)
        await s.commit()
        query = text("SELECT count(*) FROM sources WHERE name = 'ted'")
        count = (await s.execute(query)).scalar_one()
    assert a == b
    assert count == 1


async def test_save_inserts_fields_and_is_idempotent(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    d = doc("https://x.test/1", T0)
    async with maker() as s:
        first = await save_documents(s, [d])
        again = await save_documents(s, [d])
        await s.commit()
        row = (await s.execute(text("SELECT * FROM documents"))).mappings().one()
    assert (first.inserted, first.unchanged) == (1, 0)
    assert (again.inserted, again.unchanged) == (0, 1)
    assert row["text"] == d.text
    assert row["content_hash"] == d.content_hash
    assert row["external_id"] == "e1"
    assert row["workspace_id"] is None
    assert row["meta"]["date_flags"] == ["missing_publication"]
    assert row["meta"]["language"] == "en"
    assert row["meta"]["source"] == "web"
    assert row["meta"]["tier"] == "company"
    assert row["meta"]["when"] == "2026-01-02"


async def test_available_as_of_filters(maker: async_sessionmaker[AsyncSession]) -> None:
    docs = [
        doc("https://x.test/past", T0 - timedelta(days=1), group_key="g"),
        doc("https://x.test/exact", T0, source="other"),
        doc("https://x.test/future", T0 + timedelta(seconds=1), group_key="g"),
        doc("https://x.test/null", None),
    ]
    async with maker() as s:
        await save_documents(s, docs)
        await s.commit()
        got = await documents_available_as_of(s, T0)
        assert {d.url for d in got} == {"https://x.test/past", "https://x.test/exact"}
        assert_available(got, T0)
        only = await documents_available_as_of(s, T0, source_names=["other"])
        assert [d.url for d in only] == ["https://x.test/exact"]
        grp = await documents_available_as_of(s, T0 + timedelta(days=1), group_key="g")
        assert {d.url for d in grp} == {"https://x.test/past", "https://x.test/future"}
        assert len(await documents_available_as_of(s, T0, limit=1)) == 1
