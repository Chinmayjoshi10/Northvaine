"""Discover and lead upgrade (T5.3, D59, D65): sensors with shifted queries, then one publisher
page fetch per lead (robots, deny list, safe fetch, contacts stripped).

`http` is an httpx.AsyncClient or None; httpx is not imported here (network belongs in sensors/).
"""

from __future__ import annotations

from datetime import date
from typing import Any, Protocol

from northvaine.core.models import EvidenceDocument
from northvaine.core.settings import Settings
from northvaine.radar.models import ClientSpec, DiscoverResult, UpgradedPage
from northvaine.sensors.base import SensorQuery

__all__ = [
    "LivePageFetcher",
    "PageFetcher",
    "RecordedPageFetcher",
    "discover",
    "shift_queries",
    "strip_contacts",
    "upgraded_document",
]


def shift_queries(
    queries: dict[str, list[SensorQuery]], as_of: date
) -> dict[str, list[SensorQuery]]:
    """Shift every query's date range to end at `as_of`, keeping its length (D65)."""
    raise NotImplementedError("T5.3")


def strip_contacts(text: str) -> str:
    """Remove email addresses and phone numbers from fetched text (D59)."""
    raise NotImplementedError("T5.3")


class PageFetcher(Protocol):
    """Fetches one lead's publisher page; a refusal is a result, never an exception."""

    async def fetch(self, url: str) -> UpgradedPage: ...


class LivePageFetcher:
    """Real fetch: RobotsCache + safe_fetch + html_to_text + strip_contacts."""

    async def fetch(self, url: str) -> UpgradedPage:
        raise NotImplementedError("T5.3")


class RecordedPageFetcher:
    """Replay from a list of recorded pages; an unknown url raises ReplayMismatch."""

    async def fetch(self, url: str) -> UpgradedPage:
        raise NotImplementedError("T5.3")


def upgraded_document(page: UpgradedPage, lead: EvidenceDocument) -> EvidenceDocument | None:
    """The `website` document for a fetched page (`available_at` = fetched_at, `meta.upgraded_from`
    = lead URL), or None when the page was refused or empty."""
    raise NotImplementedError("T5.3")


async def discover(
    spec: ClientSpec,
    queries: dict[str, list[SensorQuery]],
    *,
    http: Any,  # httpx.AsyncClient | None; httpx stays out of radar imports (rule: sensors/)
    fetcher: PageFetcher,
    settings: Settings | None = None,
) -> DiscoverResult:
    """Run the sensors for `queries`, then upgrade up to `radar_max_lead_upgrades` leads."""
    raise NotImplementedError("T5.3")
