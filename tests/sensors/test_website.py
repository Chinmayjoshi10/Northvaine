from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from northvaine.core.models import SourceTier
from northvaine.core.settings import Settings
from northvaine.sensors.base import (
    ReplayUnsupported,
    RobotsDisallowed,
    SensorError,
    SensorQuery,
    content_hash,
)
from northvaine.sensors.website import WebsiteSensor

WEB = Path(__file__).parent.parent / "fixtures" / "web"
S = Settings(_env_file=None)


async def public(host: str) -> list[str]:
    return ["93.184.216.34"]


def sensor(routes: dict[str, httpx.Response | str], seen: list[str] | None = None) -> WebsiteSensor:
    async def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(str(request.url))
        route = routes.get(str(request.url))
        if route is None:
            return httpx.Response(404)
        if isinstance(route, str):
            return httpx.Response(200, text=route, headers={"content-type": "text/html"})
        return route

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return WebsiteSensor(client=client, resolver=public, settings=S)


def site() -> dict[str, str]:
    return {
        "https://acme.test/": (WEB / "home.html").read_text(encoding="utf-8"),
        "https://acme.test/about": (WEB / "about.html").read_text(encoding="utf-8"),
        "https://acme.test/products/list": (WEB / "products.html").read_text(encoding="utf-8"),
        "https://acme.test/blog/post-1": "<p>blog</p>",
        "https://other.example.org/about": "<p>elsewhere</p>",
    }


async def test_snapshot_follows_useful_same_domain_links_only():
    seen: list[str] = []
    result = await sensor(site(), seen).snapshot("https://acme.test/")
    urls = [d.url for d in result.documents]
    assert urls == [
        "https://acme.test/",
        "https://acme.test/about",
        "https://acme.test/products/list",
    ]
    assert "https://acme.test/blog/post-1" not in seen
    assert not any("other.example.org" in u for u in seen)
    assert result.enumerable is False
    assert not result.truncated


async def test_document_shape():
    result = await sensor(site()).snapshot("https://acme.test/")
    doc = result.documents[0]
    assert doc.tier is SourceTier.COMPANY
    assert doc.source == "website"
    assert doc.published_on is None
    assert doc.available_at == doc.fetched_at
    assert doc.content_hash == content_hash(doc.text)
    assert doc.title == "Acme Works"
    assert "<script" not in doc.text
    assert "ignore previous instructions" in doc.text


async def test_max_pages_caps_and_flags_truncated():
    result = await sensor(site()).snapshot("https://acme.test/", max_pages=2)
    assert len(result.documents) == 2
    assert result.truncated


async def test_robots_disallowed_start_page_raises():
    routes = site()
    routes["https://acme.test/robots.txt"] = "User-agent: *\nDisallow: /\n"
    with pytest.raises(RobotsDisallowed):
        await sensor(routes).snapshot("https://acme.test/")


async def test_robots_disallowed_subpage_skipped_with_note():
    routes = site()
    routes["https://acme.test/robots.txt"] = "User-agent: *\nDisallow: /about\n"
    result = await sensor(routes).snapshot("https://acme.test/")
    assert all(d.url != "https://acme.test/about" for d in result.documents)
    assert any("/about" in n for n in result.notes)


async def test_failing_subpage_skipped_start_page_error_raised():
    routes = site()
    del routes["https://acme.test/about"]
    result = await sensor(routes).snapshot("https://acme.test/")
    assert len(result.documents) == 2
    assert any("HTTP 404" in n for n in result.notes)


async def test_search_uses_text_as_url():
    result = await sensor(site()).search(SensorQuery(text="https://acme.test/"))
    assert len(result.documents) == 3


async def test_search_non_url_raises_sensor_error():
    with pytest.raises(SensorError):
        await sensor(site()).search(SensorQuery(text="acme widgets"))
    with pytest.raises(SensorError):
        await sensor(site()).search(SensorQuery())


async def test_search_with_as_of_unsupported():
    with pytest.raises(ReplayUnsupported):
        await sensor(site()).search(
            SensorQuery(text="https://acme.test/"), as_of=datetime(2026, 1, 1, tzinfo=UTC)
        )


async def test_private_start_url_blocked():
    from northvaine.sensors.base import FetchBlocked

    with pytest.raises(FetchBlocked):
        await sensor(site()).snapshot("http://127.0.0.1/")
