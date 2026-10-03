"""Tavily search sensor (M3): the specification/announcement stream, not enumerable (D30).

The request builder is frozen here; parsing and the sensor are T3.5's. The API key goes only in
the Authorization: Bearer header, never in the body.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any, ClassVar

from northvaine.core.models import SourceTier
from northvaine.core.settings import Settings, get_settings
from northvaine.core.standards import iso2_to_name
from northvaine.sensors.base import SensorDocument, SensorQuery, SensorResult

if TYPE_CHECKING:
    import httpx

TAVILY_MAX_RESULTS = 20


def build_search_request(
    query: SensorQuery, *, settings: Settings | None = None
) -> tuple[dict[str, Any], list[str]]:
    """The Tavily /search body and human-readable notes about what was left out.

    `query.text` is required (ValueError otherwise). `country` (lowercase English name) is sent
    only for exactly one country. `days`, `auto_parameters` and the API key never appear.
    """
    settings = settings or get_settings()
    if query.text is None or not query.text.strip():
        raise ValueError("a Tavily search needs query.text")
    notes: list[str] = []
    body: dict[str, Any] = {
        "query": query.text,
        "topic": "general",
        "search_depth": "basic",
        "max_results": min(TAVILY_MAX_RESULTS, query.max_results),
        "include_raw_content": "text",
        "include_published_date": True,
        "include_usage": True,
    }
    if query.published_from is not None:
        body["start_date"] = query.published_from.isoformat()
    if query.published_to is not None:
        body["end_date"] = query.published_to.isoformat()
    if len(query.countries) == 1:
        body["country"] = iso2_to_name(query.countries[0])
    elif len(query.countries) > 1:
        notes.append("country omitted: Tavily accepts exactly one country, query has several")
    return body, notes


def parse_result(result: dict[str, Any], *, fetched_at: datetime) -> SensorDocument:
    """One Tavily result to a SensorDocument (available_at = fetched_at, D37). T3.5."""
    raise NotImplementedError("T3.5")


class TavilySensor:
    """Tavily search as a sensor. Not enumerable. T3.5."""

    name: ClassVar[str] = "tavily"
    tier: ClassVar[SourceTier] = SourceTier.REPORTED
    enumerable: ClassVar[bool] = False

    def __init__(
        self, client: httpx.AsyncClient | None = None, settings: Settings | None = None
    ) -> None:
        raise NotImplementedError("T3.5")

    async def search(
        self,
        query: SensorQuery,
        *,
        as_of: datetime | None = None,
        cursor: str | None = None,
    ) -> SensorResult:
        raise NotImplementedError("T3.5")
