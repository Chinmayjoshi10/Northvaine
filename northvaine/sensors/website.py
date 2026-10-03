"""Website snapshot sensor (T3.2): a client's own public pages as documents."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, ClassVar
from urllib.parse import urlsplit

from northvaine.core.models import SourceTier
from northvaine.core.settings import Settings, get_settings
from northvaine.sensors.base import (
    ReplayUnsupported,
    SensorDocument,
    SensorError,
    SensorQuery,
    SensorResult,
    content_hash,
)
from northvaine.sensors.fetch import Resolver, RobotsCache, safe_fetch
from northvaine.sensors.html_text import extract_links, html_to_text

if TYPE_CHECKING:
    import httpx

# Generic page-purpose words only; never industry terms (rule 1).
_PAGE_HINTS = (
    "about", "product", "service", "contact", "company", "team", "who-we-are",
    "what-we-do", "solutions", "catalog", "capabilities",
)  # fmt: skip
_SECOND_LEVEL = {"co", "com", "org", "net", "gov", "ac", "edu"}


def _registrable(host: str) -> str:
    labels = host.lower().rstrip(".").split(".")
    if len(labels) >= 3 and len(labels[-1]) == 2 and labels[-2] in _SECOND_LEVEL:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


def _looks_useful(url: str) -> bool:
    path = urlsplit(url).path.lower()
    return any(hint in path for hint in _PAGE_HINTS)


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
        self._client = client
        self._resolver = resolver
        self._settings = settings or get_settings()

    async def snapshot(self, url: str, *, max_pages: int = 10) -> SensorResult:
        robots = RobotsCache()
        domain = _registrable(urlsplit(url).hostname or "")
        docs: list[SensorDocument] = []
        notes: list[str] = []
        queue = [url]
        seen = {url}
        truncated = False
        while queue:
            if len(docs) >= max_pages:
                truncated = True
                break
            current = queue.pop(0)
            try:
                await robots.ensure_allowed(
                    current,
                    client=self._client,
                    resolver=self._resolver,
                    settings=self._settings,
                )
                page = await safe_fetch(
                    current,
                    client=self._client,
                    resolver=self._resolver,
                    settings=self._settings,
                )
            except SensorError as exc:
                if current == url:
                    raise
                notes.append(f"skipped {current}: {exc}")
                continue
            if page.status >= 400:
                notes.append(f"skipped {current}: HTTP {page.status}")
                continue
            ctype = (page.content_type or "").lower()
            if ctype and "html" not in ctype and "text" not in ctype:
                notes.append(f"skipped {current}: content type {ctype}")
                continue
            title, text = html_to_text(page.text)
            docs.append(
                SensorDocument(
                    source=self.name,
                    tier=self.tier,
                    url=page.final_url,
                    title=title,
                    text=text,
                    content_hash=content_hash(text),
                    published_on=None,
                    fetched_at=page.fetched_at,
                    available_at=page.fetched_at,
                )
            )
            if current == url:
                for link in extract_links(page.text, page.final_url):
                    link_host = urlsplit(link).hostname or ""
                    if link in seen or _registrable(link_host) != domain:
                        continue
                    if _looks_useful(link):
                        seen.add(link)
                        queue.append(link)
        return SensorResult(documents=docs, truncated=truncated, enumerable=False, notes=notes)

    async def search(
        self,
        query: SensorQuery,
        *,
        as_of: datetime | None = None,
        cursor: str | None = None,
    ) -> SensorResult:
        if as_of is not None:
            raise ReplayUnsupported("website snapshots are live; they cannot be replayed")
        text = (query.text or "").strip()
        parts = urlsplit(text)
        if parts.scheme not in ("http", "https") or not parts.netloc:
            raise SensorError("website search needs query.text to be an http(s) URL")
        return await self.snapshot(text, max_pages=min(10, query.max_results))
