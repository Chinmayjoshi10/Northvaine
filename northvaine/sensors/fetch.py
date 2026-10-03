"""Safe fetch (rules #7, #9): public http(s) only, deny list, size and redirect caps. T3.2.

Every hop is checked before any request: scheme, deny-listed host, then each resolved address
must be globally routable. Bodies are streamed and cut at `fetch_max_bytes`. DNS rebinding
(httpx resolves again on connect) is a known residual, parked in docs/LATER.md.
"""

from __future__ import annotations

import asyncio
import ipaddress
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

from northvaine.core.models import NorthvaineModel
from northvaine.core.settings import Settings, get_settings
from northvaine.sensors.base import FetchBlocked, RobotsDisallowed, SensorError

if TYPE_CHECKING:
    import httpx

Resolver = Callable[[str], Awaitable[list[str]]]

_CGNAT = ipaddress.ip_network("100.64.0.0/10")
_REDIRECT_STATUSES = {301, 302, 303, 307, 308}


class FetchedPage(NorthvaineModel):
    url: str
    final_url: str
    status: int
    content_type: str | None = None
    text: str
    fetched_at: datetime


def is_public_ip(addr: str) -> bool:
    """True only for a globally routable address (IPv4, IPv6, IPv4-mapped IPv6)."""
    try:
        ip = ipaddress.ip_address(addr.strip().strip("[]").split("%")[0])
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped is not None:
            return is_public_ip(str(ip.ipv4_mapped))
        if ip.sixtofour is not None and not is_public_ip(str(ip.sixtofour)):
            return False
    if ip in _CGNAT:
        return False
    return not (
        ip.is_loopback
        or ip.is_private
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
        or not ip.is_global
    )


def host_denied(host: str, deny_hosts: Sequence[str]) -> bool:
    """True when `host` is, or is a subdomain of, a denied host."""
    h = host.lower().rstrip(".")
    for denied in deny_hosts:
        d = denied.lower().strip().rstrip(".")
        if d and (h == d or h.endswith("." + d)):
            return True
    return False


async def _default_resolver(host: str) -> list[str]:
    loop = asyncio.get_running_loop()
    infos = await loop.getaddrinfo(host, None)
    return [str(info[4][0]) for info in infos]


async def _check_url(url: str, resolver: Resolver, settings: Settings) -> None:
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise FetchBlocked(f"scheme {parts.scheme!r} is not allowed")
    host = parts.hostname
    if not host:
        raise FetchBlocked("URL has no host")
    if host_denied(host, settings.fetch_deny_hosts):
        raise FetchBlocked(f"host {host!r} is on the deny list")
    try:
        ipaddress.ip_address(host)
        addrs = [host]
    except ValueError:
        try:
            addrs = await resolver(host)
        except OSError as exc:
            raise FetchBlocked(f"cannot resolve {host!r}") from exc
    if not addrs:
        raise FetchBlocked(f"cannot resolve {host!r}")
    for addr in addrs:
        if not is_public_ip(addr):
            raise FetchBlocked(f"host {host!r} resolves to a non-public address")


async def _read_capped(response: httpx.Response, limit: int) -> bytes:
    chunks: list[bytes] = []
    size = 0
    async for chunk in response.aiter_bytes():
        remaining = limit - size
        if len(chunk) >= remaining:
            chunks.append(chunk[:remaining])
            break
        chunks.append(chunk)
        size += len(chunk)
    return b"".join(chunks)


async def _fetch(
    url: str, client: httpx.AsyncClient, resolver: Resolver, settings: Settings
) -> FetchedPage:
    import httpx  # lazy: importing the module must not load the network client

    current = url
    for _hop in range(settings.fetch_max_redirects + 1):
        await _check_url(current, resolver, settings)
        request = client.build_request(
            "GET", current, headers={"User-Agent": settings.fetch_user_agent}
        )
        try:
            response = await client.send(request, stream=True, follow_redirects=False)
        except httpx.TimeoutException as exc:
            raise SensorError(f"timeout fetching {current}") from exc
        except httpx.HTTPError as exc:
            raise SensorError(f"fetch failed for {current}: {type(exc).__name__}") from exc
        try:
            if response.status_code in _REDIRECT_STATUSES and "location" in response.headers:
                current = urljoin(current, response.headers["location"])
                continue
            body = await _read_capped(response, settings.fetch_max_bytes)
            text = body.decode(response.encoding or "utf-8", errors="replace")
            return FetchedPage(
                url=url,
                final_url=current,
                status=response.status_code,
                content_type=response.headers.get("content-type"),
                text=text,
                fetched_at=datetime.now(UTC),
            )
        finally:
            await response.aclose()
    raise FetchBlocked(f"too many redirects (max {settings.fetch_max_redirects})")


async def safe_fetch(
    url: str,
    *,
    client: httpx.AsyncClient | None = None,
    resolver: Resolver | None = None,
    settings: Settings | None = None,
) -> FetchedPage:
    """Fetch one public page; raises FetchBlocked when refused. Non-2xx statuses are returned."""
    settings = settings or get_settings()
    resolver = resolver or _default_resolver
    owned = client is None
    if client is None:
        import httpx

        http = httpx.AsyncClient(timeout=settings.fetch_timeout_seconds)
    else:
        http = client
    try:
        async with asyncio.timeout(settings.fetch_timeout_seconds):
            return await _fetch(url, http, resolver, settings)
    except TimeoutError as exc:
        raise SensorError(f"timeout fetching {url}") from exc
    finally:
        if owned:
            await http.aclose()


class RobotsCache:
    """robots.txt per host, fetched once and cached."""

    def __init__(self) -> None:
        self._parsers: dict[str, RobotFileParser | bool] = {}  # bool: allow-all / deny-all
        self._locks: dict[str, asyncio.Lock] = {}

    async def _load(
        self,
        origin: str,
        client: httpx.AsyncClient | None,
        resolver: Resolver | None,
        settings: Settings,
    ) -> RobotFileParser | bool:
        try:
            page = await safe_fetch(
                origin + "/robots.txt", client=client, resolver=resolver, settings=settings
            )
        except FetchBlocked:
            raise
        except SensorError:
            return False
        if page.status == 200:
            parser = RobotFileParser()
            parser.parse(page.text.splitlines())
            return parser
        return page.status < 500

    async def allowed(
        self,
        url: str,
        *,
        client: httpx.AsyncClient | None = None,
        resolver: Resolver | None = None,
        settings: Settings | None = None,
    ) -> bool:
        settings = settings or get_settings()
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        lock = self._locks.setdefault(origin, asyncio.Lock())
        async with lock:
            if origin not in self._parsers:
                self._parsers[origin] = await self._load(origin, client, resolver, settings)
        entry = self._parsers[origin]
        if isinstance(entry, bool):
            return entry
        return entry.can_fetch(settings.fetch_user_agent, url)

    async def ensure_allowed(
        self,
        url: str,
        *,
        client: httpx.AsyncClient | None = None,
        resolver: Resolver | None = None,
        settings: Settings | None = None,
    ) -> None:
        """Like `allowed`, but raises RobotsDisallowed when robots.txt forbids the URL."""
        if not await self.allowed(url, client=client, resolver=resolver, settings=settings):
            raise RobotsDisallowed(f"robots.txt forbids fetching {url}")
