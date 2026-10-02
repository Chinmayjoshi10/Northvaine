"""First test — health check. Run with: pytest tests/ -x"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from northvaine.api.main import app


@pytest.mark.asyncio
async def test_health() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
