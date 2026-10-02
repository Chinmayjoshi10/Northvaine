"""Health check endpoint (async test; pytest-asyncio auto mode, no marker needed)."""

from __future__ import annotations

from httpx import ASGITransport, AsyncClient

from northvaine.api.main import app


async def test_health() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
