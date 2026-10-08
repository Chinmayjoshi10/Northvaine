"""Tavily search sensor (M3): the specification/announcement stream, not enumerable (D30).

The request builder is frozen here; parsing and the sensor are T3.5's. The API key goes only in
the Authorization: Bearer header, never in the body.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, ClassVar
from urllib.parse import urlsplit

from northvaine.core.models import SourceTier
from northvaine.core.settings import ConfigError, Settings, get_settings
from northvaine.core.standards import iso2_to_name
from northvaine.sensors.base import (
    DateFlag,
    ReplayUnsupported,
    SensorDocument,
    SensorError,
    SensorQuery,
    SensorRateLimited,
    SensorResult,
    content_hash,
)
from northvaine.sensors.dates import parse_date
from northvaine.sensors.fetch import host_denied

if TYPE_CHECKING:
    import httpx

TAVILY_MAX_RESULTS = 20

log = logging.getLogger(__name__)


class TavilyBudgetStopError(SensorError):
    """Tavily or our own per-run cap says stop (HTTP 432/433, or the call counter). Not retried."""

    budget_stop = True


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
    if query.domains:
        body["include_domains"] = list(query.domains)
    if len(query.countries) == 1:
        body["country"] = iso2_to_name(query.countries[0])
    elif len(query.countries) > 1:
        notes.append("country omitted: Tavily accepts exactly one country, query has several")
    return body, notes


def parse_result(result: dict[str, Any], *, fetched_at: datetime) -> SensorDocument:
    """One Tavily result to a SensorDocument (available_at = fetched_at, D37).

    The text is untrusted third-party data. Snippet-only text is marked `meta.text_kind='snippet'`
    so that no claim is ever verified against it (rule #2). The published date is only what the
    page claims, so it is always flagged `claimed_date_untrusted`.
    """
    url = result.get("url")
    if not isinstance(url, str) or not url.strip():
        raise ValueError("Tavily result has no url")
    raw = result.get("raw_content")
    snippet = result.get("content")
    if isinstance(raw, str) and raw.strip():
        text, kind = raw, "raw"
    elif isinstance(snippet, str) and snippet.strip():
        text, kind = snippet, "snippet"
    else:
        raise ValueError("Tavily result has no text")
    title = result.get("title")
    claimed = result.get("published_date")
    flags = [DateFlag.CLAIMED_DATE_UNTRUSTED]
    published_on = parse_date(claimed) if isinstance(claimed, str) else None
    if claimed not in (None, "") and published_on is None:
        flags.append(DateFlag.UNPARSEABLE)
    meta: dict[str, Any] = {
        "text_kind": kind,
        "score": result.get("score"),
        "published_date": claimed,
    }
    return SensorDocument(
        source=TavilySensor.name,
        tier=TavilySensor.tier,
        url=url,
        title=title if isinstance(title, str) and title.strip() else None,
        text=text,
        content_hash=content_hash(text),
        published_on=published_on,
        fetched_at=fetched_at,
        available_at=fetched_at,
        meta=meta,
        date_flags=flags,
    )


def _retry_after(response: httpx.Response) -> float | None:
    value = response.headers.get("retry-after")
    try:
        return float(value) if value is not None else None
    except ValueError:
        return None  # an HTTP-date form: treated as unstated


class TavilySensor:
    """Tavily search as a sensor. Not enumerable: recall cannot be measured (D30)."""

    name: ClassVar[str] = "tavily"
    tier: ClassVar[SourceTier] = SourceTier.REPORTED
    enumerable: ClassVar[bool] = False

    def __init__(
        self, client: httpx.AsyncClient | None = None, settings: Settings | None = None
    ) -> None:
        self._client = client
        self._settings = settings or get_settings()
        self._calls = 0

    def _api_key(self) -> str:
        key = self._settings.tavily_api_key
        value = key.get_secret_value() if key is not None else ""
        if not value:
            raise ConfigError("TAVILY_API_KEY is not set")
        return value

    def _new_client(self) -> httpx.AsyncClient:
        import httpx  # lazy: importing this module needs no network library

        return httpx.AsyncClient(timeout=self._settings.fetch_timeout_seconds)

    async def _post(self, client: httpx.AsyncClient, body: dict[str, Any], key: str) -> Any:
        limit = self._settings.tavily_max_calls_per_run
        if self._calls >= limit:
            raise TavilyBudgetStopError(f"Tavily call cap reached ({limit} per run)")
        self._calls += 1
        url = self._settings.tavily_api_url.rstrip("/") + "/search"
        response = await client.post(url, json=body, headers={"Authorization": f"Bearer {key}"})
        status = response.status_code
        if status == 429:
            raise SensorRateLimited(
                "Tavily rate limit (HTTP 429)", retry_after=_retry_after(response)
            )
        if status in (432, 433):
            raise TavilyBudgetStopError(f"Tavily plan or usage limit reached (HTTP {status})")
        if status == 401:
            raise SensorError("Tavily rejected the API key (HTTP 401)")
        if status >= 400:
            raise SensorError(f"Tavily returned HTTP {status}")
        try:
            data = response.json()
        except ValueError:
            raise SensorError("Tavily returned a non-JSON response") from None
        if not isinstance(data, dict):
            raise SensorError("Tavily returned an unexpected response shape")
        return data

    async def search(
        self,
        query: SensorQuery,
        *,
        as_of: datetime | None = None,
        cursor: str | None = None,
    ) -> SensorResult:
        """One /search call. Live web cannot be replayed, so any `as_of` is refused."""
        if as_of is not None:
            raise ReplayUnsupported("Tavily is live web and cannot honour as_of (ARCHITECTURE 23)")
        body, notes = build_search_request(query, settings=self._settings)
        key = self._api_key()
        client = self._client or self._new_client()
        try:
            data = await self._post(client, body, key)
        finally:
            if self._client is None:
                await client.aclose()
        fetched_at = datetime.now(UTC)
        results = data.get("results")
        docs: list[SensorDocument] = []
        denied = skipped = 0
        for item in results if isinstance(results, list) else []:
            if not isinstance(item, dict):
                skipped += 1
                continue
            host = urlsplit(str(item.get("url") or "")).hostname
            if host and host_denied(host, self._settings.fetch_deny_hosts):
                denied += 1  # rule #9: never use results from sites that forbid scraping
                continue
            try:
                docs.append(parse_result(item, fetched_at=fetched_at))
            except ValueError:
                skipped += 1
        if denied:
            notes.append(f"{denied} result(s) dropped: host is on the deny list")
        if skipped:
            notes.append(f"{skipped} result(s) skipped: no url or no text")
        log.debug("tavily search returned %d documents", len(docs))
        return SensorResult(
            documents=docs, truncated=False, enumerable=self.enumerable, notes=notes
        )
