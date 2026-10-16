"""Contact requests and the one free radar per email (D104). Tmp reports dir; no network."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from pathlib import Path

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from northvaine.api.accounts import REQUESTS, SUBSCRIBERS, TRIALS, reports
from northvaine.api.main import app


@pytest_asyncio.fixture
async def client(tmp_path: Path) -> AsyncIterator[tuple[AsyncClient, Path]]:
    app.dependency_overrides[reports] = lambda: tmp_path
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c, tmp_path
    app.dependency_overrides.clear()


FORM = {
    "kind": "subscribe",
    "name": "Test Person",
    "company": "Example Trading Ltd",
    "email": "Buyer@Example.test",
    "website": "example.test",
    "message": "We export paving.",
}


async def test_contact_is_stored(client: tuple[AsyncClient, Path]) -> None:
    c, base = client
    r = await c.post("/api/contact", json=FORM)
    assert r.status_code == 201 and r.json() == {"received": True}
    (line,) = (base / REQUESTS).read_text(encoding="utf-8").splitlines()
    saved = json.loads(line)
    assert saved["email"] == "buyer@example.test" and saved["company"] == "Example Trading Ltd"
    assert "website_url" not in saved and saved["received_at"]


async def test_bot_field_is_accepted_and_dropped(client: tuple[AsyncClient, Path]) -> None:
    c, base = client
    r = await c.post("/api/contact", json={**FORM, "website_url": "http://spam.test"})
    assert r.status_code == 201
    assert not (base / REQUESTS).exists()


async def test_bad_email_is_refused(client: tuple[AsyncClient, Path]) -> None:
    c, _ = client
    r = await c.post("/api/contact", json={**FORM, "email": "not-an-email"})
    assert r.status_code == 422


async def test_one_free_radar_per_email(client: tuple[AsyncClient, Path]) -> None:
    c, base = client
    first = await c.post("/api/trial", json={"email": "Owner@Example.test"})
    assert first.status_code == 201 and first.json() == {"status": "free"}
    again = await c.post("/api/trial", json={"email": "owner@example.test"})
    assert again.status_code == 409
    assert len((base / TRIALS).read_text(encoding="utf-8").splitlines()) == 1


async def test_subscribers_are_not_limited(client: tuple[AsyncClient, Path]) -> None:
    c, base = client
    (base / SUBSCRIBERS).write_text("# paid\nowner@example.test\n", encoding="utf-8")
    for _ in range(2):
        r = await c.post("/api/trial", json={"email": "owner@example.test"})
        assert r.status_code == 201 and r.json() == {"status": "subscriber"}
