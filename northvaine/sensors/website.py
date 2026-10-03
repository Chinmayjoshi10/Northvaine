"""Website snapshot sensor (T3.2): a client's own public pages as documents."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, ClassVar

from northvaine.core.models import SourceTier
from northvaine.core.settings import Settings
from northvaine.sensors.base import SensorQuery, SensorResult
from northvaine.sensors.fetch import Resolver

if TYPE_CHECKING:
    import httpx


class WebsiteSensor:
    """Live pages only: refuses `as_of` (ReplayUnsupported). Not enumerable."""

    name: ClassVar[str] = "website"
    tier: ClassVar[SourceTier] = SourceTier.COMPANY
    enumerable: ClassVar[bool] = False

    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        resolver: Resolver | None = None,
        settings: Settings | None = None,
    ) -> None:
        raise NotImplementedError("T3.2")

    async def snapshot(self, url: str, *, max_pages: int = 10) -> SensorResult:
        raise NotImplementedError("T3.2")

    async def search(
        self,
        query: SensorQuery,
        *,
        as_of: datetime | None = None,
        cursor: str | None = None,
    ) -> SensorResult:
        raise NotImplementedError("T3.2")
