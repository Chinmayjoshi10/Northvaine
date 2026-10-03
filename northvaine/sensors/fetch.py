"""Safe fetch (rules #7, #9): public http(s) only, deny list, size and redirect caps. T3.2."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from datetime import datetime
from typing import TYPE_CHECKING

from northvaine.core.models import NorthvaineModel
from northvaine.core.settings import Settings

if TYPE_CHECKING:
    import httpx

Resolver = Callable[[str], Awaitable[list[str]]]


class FetchedPage(NorthvaineModel):
    url: str
    final_url: str
    status: int
    content_type: str | None = None
    text: str
    fetched_at: datetime


def is_public_ip(addr: str) -> bool:
    """True only for a globally routable address. T3.2."""
    raise NotImplementedError("T3.2")


def host_denied(host: str, deny_hosts: Sequence[str]) -> bool:
    """True when `host` is, or is a subdomain of, a denied host. T3.2."""
    raise NotImplementedError("T3.2")


async def safe_fetch(
    url: str,
    *,
    client: httpx.AsyncClient | None = None,
    resolver: Resolver | None = None,
    settings: Settings | None = None,
) -> FetchedPage:
    """Fetch one public page; raises FetchBlocked or RobotsDisallowed when refused. T3.2."""
    raise NotImplementedError("T3.2")


class RobotsCache:
    """robots.txt per host, fetched once and cached. T3.2."""

    async def allowed(
        self,
        url: str,
        *,
        client: httpx.AsyncClient | None = None,
        resolver: Resolver | None = None,
        settings: Settings | None = None,
    ) -> bool:
        raise NotImplementedError("T3.2")
