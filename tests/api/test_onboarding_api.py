"""Onboarding API (D105): the free-radar claim, catalogue upload, proposal and run steps, with
the website reader, the model call and the radar run replaced by stand-ins. No network."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from northvaine.api import onboarding
from northvaine.api.main import app
from northvaine.radar.onboarding import Proposal

START = {"email": "owner@example.test", "company": "Example Works", "website": "example.test"}
PROPOSAL = Proposal(
    offer="Maker of garden benches.",
    offer_terms=["garden benches"],
    markets=["GB"],
    buyer_roles=["retailers"],
    hs_codes=["940179", "999999"],
)


@pytest_asyncio.fixture
async def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[AsyncClient]:
    async def read_site(base: Path, sid: str, website: str) -> None:
        (onboarding._dir(base) / f"{sid}.site.txt").write_text("garden benches", encoding="utf-8")
        onboarding._update(base, sid, stage="ready", site_read=True)

    async def fake_propose(site: str, catalogue: str, **_: Any) -> Proposal:
        assert "garden benches" in site
        return PROPOSAL

    async def known(codes: list[str], **_: Any) -> dict[str, str]:
        return {c: "Seats" for c in codes if c == "940179"}

    monkeypatch.setattr(onboarding, "_read_site", read_site)
    monkeypatch.setattr(onboarding, "propose", fake_propose)
    monkeypatch.setattr("northvaine.sensors.hmrc.hs6_descriptions", known)

    async def all_match(_offer: str, _terms: list[str], described: dict[str, str], **_: Any):
        return list(described), []

    monkeypatch.setattr(onboarding, "check_codes", all_match)  # never a real model call (D141)
    app.dependency_overrides[onboarding.reports] = lambda: tmp_path
    app.dependency_overrides[onboarding.accounts.reports] = lambda: tmp_path
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


async def wait_for(c: AsyncClient, sid: str, stage: str) -> dict[str, Any]:
    for _ in range(100):
        body = (await c.get(f"/api/onboarding/{sid}")).json()
        if body["stage"] == stage:
            return body
        await asyncio.sleep(0.02)
    raise AssertionError(f"stage {stage} not reached: {body}")


async def test_start_claims_the_free_radar_once(client: AsyncClient) -> None:
    first = await client.post("/api/onboarding", json=START)
    assert first.status_code == 201
    again = await client.post("/api/onboarding", json=START)
    assert again.status_code == 409


async def test_catalogue_must_be_a_pdf(client: AsyncClient) -> None:
    sid = (await client.post("/api/onboarding", json=START)).json()["id"]
    r = await client.post(
        f"/api/onboarding/{sid}/catalogue", content=b"hello", headers={"content-type": "text/plain"}
    )
    assert r.status_code == 415
    r = await client.post(
        f"/api/onboarding/{sid}/catalogue",
        content=b"not a pdf",
        headers={"content-type": "application/pdf"},
    )
    assert r.status_code == 422


async def test_proposal_drops_codes_not_in_the_tariff(client: AsyncClient) -> None:
    sid = (await client.post("/api/onboarding", json=START)).json()["id"]
    await wait_for(client, sid, "ready")
    await client.post(f"/api/onboarding/{sid}/propose")
    body = await wait_for(client, sid, "proposed")
    assert body["proposal"]["hs_codes"] == ["940179"]
    assert any("999999" in d for d in body["proposal"]["dropped"])


async def test_answers_write_the_spec_and_run(
    client: AsyncClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from northvaine.radar import live

    monkeypatch.setattr(onboarding, "REPO_ROOT", tmp_path)
    monkeypatch.setenv("ONBOARDING_CLIENTS_DIR", str(tmp_path / "clients"))
    from northvaine.core.settings import get_settings

    get_settings.cache_clear()
    ran: list[str] = []
    seen: list[Any] = []

    async def fake_run(spec: Any, *, as_of: datetime, settings: Any, progress: Any = None) -> Any:
        ran.append(spec.id)
        seen.append(settings)
        progress("Reading your markets")
        raise RuntimeError("no network in tests")

    monkeypatch.setattr(live, "run_live", fake_run)
    sid = (await client.post("/api/onboarding", json=START)).json()["id"]
    answers = {
        "company": "Example Works",
        "website": "https://www.example.test",
        "offer": "Maker of garden benches for retailers.",
        "offer_terms": ["garden benches"],
        "markets": ["GB"],
        "buyer_roles": ["retailers"],
        "hs_codes": ["940179"],
    }
    r = await client.post(f"/api/onboarding/{sid}/answers", json=answers)
    assert r.status_code == 200 and r.json()["client_id"] == "example_test"
    assert (tmp_path / "clients" / "example_test.json").is_file()
    body = await wait_for(client, sid, "failed")
    assert ran == ["example_test"] and "stopped" in body["error"]
    # D130: the run started here is the quick one, and its stage is named for the page
    assert body["progress"] == "Reading your markets"
    for name, value in onboarding.QUICK_PROFILE.items():
        assert getattr(seen[0], name) == value
    assert get_settings().radar_skeptic_top == 30  # the shared (nightly) settings are untouched
    assert get_settings().radar_max_gate_candidates == 120  # D132
    get_settings.cache_clear()


async def test_session_offers_the_not_buyer_roles(client: AsyncClient) -> None:
    body = (await client.post("/api/onboarding", json=START)).json()
    roles = body["not_buyer_roles"]
    assert [r["key"] for r in roles] == ["haulage_forwarding", "warehousing", "cargo_handling"]
    assert all(r["label"] for r in roles)
