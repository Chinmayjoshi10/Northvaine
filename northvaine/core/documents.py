"""Document store and the available_at replay gate (T3.3).

`sensors.base` is imported for its errors and types only; it is httpx-free, so this module
never pulls httpx. Replay safety has two independent guards (ARCHITECTURE 4/11): the SQL
filter in `documents_available_as_of` and the pure `assert_available`.

Text and content_hash are stored exactly as the sensor produced them (invariant 2).
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from pydantic_core import to_jsonable_python

from northvaine.core.models import DocumentRow, NorthvaineModel, SourceTier
from northvaine.sensors.base import LeakageError, SensorDocument

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

__all__ = [
    "SaveResult",
    "assert_available",
    "documents_available_as_of",
    "ensure_source",
    "save_documents",
]

_COLUMNS = (
    "id",
    "source_id",
    "url",
    "content_hash",
    "title",
    "text",
    "published_on",
    "fetched_at",
    "workspace_id",
    "available_at",
    "external_id",
    "group_key",
    "meta",
)


class SaveResult(NorthvaineModel):
    inserted: int
    unchanged: int


async def ensure_source(session: AsyncSession, name: str, tier: SourceTier) -> UUID:
    """The id of the global provider row `name`, created if missing (idempotent)."""
    from sqlalchemy import text

    result = await session.execute(
        text(
            "INSERT INTO sources (name, tier) VALUES (:name, :tier) "
            "ON CONFLICT ON CONSTRAINT sources_name_key DO UPDATE SET name = EXCLUDED.name "
            "RETURNING id"
        ),
        {"name": name, "tier": SourceTier(tier).value},
    )
    return result.scalar_one()


def _meta_for(doc: SensorDocument) -> dict[str, Any]:
    meta: dict[str, Any] = dict(to_jsonable_python(doc.meta))
    meta["date_flags"] = [flag.value for flag in doc.date_flags]
    meta["language"] = doc.language
    meta["source"] = doc.source
    meta["tier"] = SourceTier(doc.tier).value
    return meta


async def save_documents(
    session: AsyncSession, docs: Sequence[SensorDocument], *, workspace_id: UUID | None = None
) -> SaveResult:
    """Insert snapshots; an existing (url, content_hash) is counted unchanged, not rewritten."""
    from sqlalchemy import text

    stmt = text(
        "INSERT INTO documents (source_id, url, content_hash, title, text, published_on, "
        "fetched_at, workspace_id, available_at, external_id, group_key, meta) "
        "VALUES (:source_id, :url, :content_hash, :title, :text, :published_on, :fetched_at, "
        ":workspace_id, :available_at, :external_id, :group_key, CAST(:meta AS jsonb)) "
        "ON CONFLICT (url, content_hash) DO NOTHING RETURNING id"
    )
    source_ids: dict[str, UUID] = {}
    inserted = unchanged = 0
    for doc in docs:
        if doc.source not in source_ids:
            source_ids[doc.source] = await ensure_source(session, doc.source, doc.tier)
        result = await session.execute(
            stmt,
            {
                "source_id": source_ids[doc.source],
                "url": doc.url,
                "content_hash": doc.content_hash,
                "title": doc.title,
                "text": doc.text,
                "published_on": doc.published_on,
                "fetched_at": doc.fetched_at,
                "workspace_id": workspace_id,
                "available_at": doc.available_at,
                "external_id": doc.external_id,
                "group_key": doc.group_key,
                "meta": json.dumps(_meta_for(doc)),
            },
        )
        if result.first() is None:
            unchanged += 1
        else:
            inserted += 1
    return SaveResult(inserted=inserted, unchanged=unchanged)


async def documents_available_as_of(
    session: AsyncSession,
    as_of: datetime,
    *,
    source_names: Sequence[str] | None = None,
    group_key: str | None = None,
    limit: int = 500,
) -> list[DocumentRow]:
    """Documents with available_at <= as_of. NULL available_at is never replayed."""
    from sqlalchemy import bindparam, text

    where = ["d.available_at IS NOT NULL", "d.available_at <= :as_of"]
    params: dict[str, Any] = {"as_of": as_of, "limit": limit}
    if source_names is not None:
        where.append("s.name IN :names")
        params["names"] = list(source_names)
    if group_key is not None:
        where.append("d.group_key = :group_key")
        params["group_key"] = group_key
    columns = ", ".join(f"d.{c}" for c in _COLUMNS)
    stmt = text(
        f"SELECT {columns} FROM documents d LEFT JOIN sources s ON s.id = d.source_id "
        f"WHERE {' AND '.join(where)} ORDER BY d.available_at, d.id LIMIT :limit"
    )
    if source_names is not None:
        stmt = stmt.bindparams(bindparam("names", expanding=True))
    result = await session.execute(stmt, params)
    return [DocumentRow.model_validate(dict(row)) for row in result.mappings()]


def assert_available(docs: Sequence[DocumentRow | SensorDocument], as_of: datetime) -> None:
    """Raise LeakageError for any document not yet available at `as_of` (or never available)."""
    for doc in docs:
        label = f"{doc.url} ({doc.content_hash[:12]})"
        if doc.available_at is None:
            raise LeakageError(f"document {label} has no available_at; it cannot be replayed")
        if doc.available_at > as_of:
            raise LeakageError(
                f"document {label} available_at {doc.available_at.isoformat()} "
                f"is after as_of {as_of.isoformat()}"
            )
