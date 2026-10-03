import asyncio

import httpx
import pytest

from northvaine.core.settings import Settings
from northvaine.sensors.base import FetchBlocked, RobotsDisallowed, SensorError
from northvaine.sensors.fetch import RobotsCache, host_denied, is_public_ip, safe_fetch

S = Settings(_env_file=None)


async def public(host: str) -> list[str]:
    return ["93.184.216.34"]


def resolver_for(mapping: dict[str, list[str]]):
    async def resolve(host: str) -> list[str]:
        return mapping[host]

    return resolve


def client_for(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.parametrize(
    "addr",
    [
        "127.0.0.1", "10.0.0.5", "172.16.3.4", "192.168.1.1", "169.254.169.254",
        "100.64.0.1", "100.127.255.255", "224.0.0.1", "240.0.0.1", "0.0.0.0",
        "::1", "fc00::1", "fe80::1", "ff02::1", "::", "::ffff:127.0.0.1",
        "::ffff:10.0.0.1", "::ffff:169.254.169.254", "not-an-ip",
    ],
)  # fmt: skip
def test_non_public_addresses_rejected(addr):
    assert not is_public_ip(addr)


@pytest.mark.parametrize(
    "addr", ["93.184.216.34", "8.8.8.8", "2606:2800:220:1::1", "::ffff:8.8.8.8"]
)
def test_public_addresses_accepted(addr):
    assert is_public_ip(addr)


def test_host_denied_matches_subdomains_only():
    deny = ["linkedin.com"]
    assert host_denied("www.linkedin.com", deny)
    assert host_denied("LinkedIn.com", deny)
    assert not host_denied("notlinkedin.com", deny)


async def test_scheme_must_be_http_or_https():
    async def handler(request):
        raise AssertionError("no request expected")

    for url in ("file:///etc/passwd", "ftp://example.test/x", "gopher://example.test"):
        with pytest.raises(FetchBlocked):
            await safe_fetch(url, client=client_for(handler), resolver=public, settings=S)


@pytest.mark.parametrize("addr", ["127.0.0.1", "10.1.1.1", "169.254.169.254", "100.64.0.9", "::1"])
async def test_host_resolving_to_private_address_blocked(addr):
    calls = []

    async def handler(request):
        calls.append(request)
        return httpx.Response(200)

    with pytest.raises(FetchBlocked):
        await safe_fetch(
            "http://evil.test/",
            client=client_for(handler),
            resolver=resolver_for({"evil.test": [addr]}),
            settings=S,
        )
    assert calls == []


async def test_any_private_address_among_several_blocks():
    async def handler(request):
        return httpx.Response(200)

    with pytest.raises(FetchBlocked):
        await safe_fetch(
            "http://mixed.test/",
            client=client_for(handler),
            resolver=resolver_for({"mixed.test": ["93.184.216.34", "10.0.0.1"]}),
            settings=S,
        )


async def test_ip_literal_urls_checked_without_resolver():
    async def handler(request):
        return httpx.Response(200)

    for url in ("http://127.0.0.1/", "http://[::1]/", "http://[::ffff:10.0.0.1]/"):
        with pytest.raises(FetchBlocked):
            await safe_fetch(url, client=client_for(handler), resolver=public, settings=S)


async def test_redirect_to_private_host_blocked_on_each_hop():
    seen = []

    async def handler(request):
        seen.append(str(request.url))
        return httpx.Response(302, headers={"location": "http://internal.test/admin"})

    resolver = resolver_for({"ok.test": ["93.184.216.34"], "internal.test": ["192.168.0.1"]})
    with pytest.raises(FetchBlocked):
        await safe_fetch(
            "http://ok.test/", client=client_for(handler), resolver=resolver, settings=S
        )
    assert seen == ["http://ok.test/"]


async def test_redirects_followed_and_relative_location_resolved():
    async def handler(request):
        if request.url.path == "/a":
            return httpx.Response(301, headers={"location": "/b"})
        return httpx.Response(200, text="done", headers={"content-type": "text/html"})

    page = await safe_fetch(
        "http://ok.test/a", client=client_for(handler), resolver=public, settings=S
    )
    assert page.final_url == "http://ok.test/b"
    assert page.url == "http://ok.test/a"
    assert page.text == "done"
    assert page.status == 200


async def test_too_many_redirects_blocked():
    async def handler(request):
        return httpx.Response(302, headers={"location": "/loop"})

    settings = Settings(_env_file=None, fetch_max_redirects=2)
    with pytest.raises(FetchBlocked, match="redirect"):
        await safe_fetch(
            "http://ok.test/", client=client_for(handler), resolver=public, settings=settings
        )


async def test_timeout_enforced():
    async def handler(request):
        await asyncio.sleep(5)
        return httpx.Response(200)

    settings = Settings(_env_file=None, fetch_timeout_seconds=0.05)
    with pytest.raises(SensorError, match="timeout"):
        await safe_fetch(
            "http://slow.test/", client=client_for(handler), resolver=public, settings=settings
        )


async def test_httpx_timeout_becomes_sensor_error():
    async def handler(request):
        raise httpx.ConnectTimeout("slow", request=request)

    with pytest.raises(SensorError, match="timeout"):
        await safe_fetch(
            "http://slow.test/", client=client_for(handler), resolver=public, settings=S
        )


async def test_body_cut_at_max_bytes():
    async def stream():
        for _ in range(100):
            yield b"x" * 100

    async def handler(request):
        return httpx.Response(200, content=stream())

    settings = Settings(_env_file=None, fetch_max_bytes=250)
    page = await safe_fetch(
        "http://big.test/", client=client_for(handler), resolver=public, settings=settings
    )
    assert len(page.text) == 250


async def test_deny_listed_host_blocked_before_any_request():
    calls = []

    async def handler(request):
        calls.append(request)
        return httpx.Response(200)

    with pytest.raises(FetchBlocked, match="deny"):
        await safe_fetch(
            "https://www.linkedin.com/company/acme",
            client=client_for(handler),
            resolver=public,
            settings=S,
        )
    assert calls == []


async def test_deny_listed_redirect_target_blocked():
    async def handler(request):
        return httpx.Response(302, headers={"location": "https://www.linkedin.com/in/x"})

    with pytest.raises(FetchBlocked, match="deny"):
        await safe_fetch("http://ok.test/", client=client_for(handler), resolver=public, settings=S)


def robots_client(status: int, body: str = "", counter: list | None = None) -> httpx.AsyncClient:
    async def handler(request):
        if counter is not None:
            counter.append(request.url.path)
        return httpx.Response(status, text=body)

    return client_for(handler)


async def test_robots_disallowed_path_raises():
    c = robots_client(200, "User-agent: *\nDisallow: /private\n")
    cache = RobotsCache()
    with pytest.raises(RobotsDisallowed):
        await cache.ensure_allowed(
            "http://ok.test/private/x", client=c, resolver=public, settings=S
        )
    assert await cache.allowed("http://ok.test/public", client=c, resolver=public, settings=S)


async def test_robots_404_allows():
    c = robots_client(404)
    assert await RobotsCache().allowed("http://ok.test/x", client=c, resolver=public, settings=S)


async def test_robots_5xx_denies():
    c = robots_client(503)
    assert not await RobotsCache().allowed(
        "http://ok.test/x", client=c, resolver=public, settings=S
    )


async def test_robots_fetched_once_per_host():
    counter: list[str] = []
    c = robots_client(200, "User-agent: *\nDisallow:\n", counter)
    cache = RobotsCache()
    for path in ("/a", "/b", "/c"):
        await cache.allowed(f"http://ok.test{path}", client=c, resolver=public, settings=S)
    assert counter == ["/robots.txt"]


async def test_robots_goes_through_safe_path():
    c = robots_client(200, "")
    resolver = resolver_for({"evil.test": ["10.0.0.1"]})
    with pytest.raises(FetchBlocked):
        await RobotsCache().allowed("http://evil.test/x", client=c, resolver=resolver, settings=S)
