"""Document store and the available_at replay gate (T3.3).

Sensor imports are for typing only, so this module never pulls httpx.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from northvaine.core.models import DocumentRow, NorthvaineModel, SourceTier

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from northvaine.sensors.base import SensorDocument


class SaveResult(NorthvaineModel):
    inserted: int
    unchanged: int


async def ensure_source(session: AsyncSession, name: str, tier: SourceTier) -> UUID:
    """The id of the global provider row `name`, created if missing. T3.3."""
    raise NotImplementedError("T3.3")


async def save_documents(
    session: AsyncSession, docs: Sequence[SensorDocument], *, workspace_id: UUID | None = None
) -> SaveResult:
    """Insert snapshots; an unchanged (url, content_hash) is not inserted again. T3.3."""
    raise NotImplementedError("T3.3")


async def documents_available_as_of(
    session: AsyncSession,
    as_of: datetime,
    *,
    source_names: Sequence[str] | None = None,
    group_key: str | None = None,
    limit: int = 500,
) -> list[DocumentRow]:
    """Documents with available_at <= as_of (NULL is never replayed). T3.3."""
    raise NotImplementedError("T3.3")


def assert_available(docs: Sequence[DocumentRow], as_of: datetime) -> None:
    """Raise LeakageError for any document not yet available at `as_of`. T3.3."""
    raise NotImplementedError("T3.3")
