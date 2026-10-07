"""Web API: runs, dossier, feedback. Synthetic run in a tmp reports dir; no network, no database."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Iterator
from datetime import date
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from northvaine.api import store
from northvaine.api.feedback import reports
from northvaine.api.main import app
from northvaine.radar import brief
from northvaine.radar.models import RadarStream
from tests.radar.test_brief import NOW, UNKNOWN, candidate, claim, gate, make_run

SCRIPT = "<script>alert(1)</script>"


@pytest.fixture
def base(tmp_path: Path) -> Iterator[Path]:
    """<tmp>/reports/radar with one client run on disk; the feedback folder is its sibling."""
    folder = tmp_path / "reports" / "radar"
    run = make_run(2)
    announced = candidate(
        "Announcer One", [claim("C1", f"Announcer One opens a site {SCRIPT}")], country="GB"
    )
    extra = brief.rank([(announced, gate(), UNKNOWN)], as_of=NOW, offer="Invented offer")
    entries = [*run.entries, *extra]
    entries = [e.model_copy(update={"rank": i + 1}) for i, e in enumerate(entries)]
    run = run.model_copy(update={"entries": entries, "client_id": "acme"})
    brief.write_reports(run, folder)
    # a likely bidder, written the way a newer build would
    path = folder / "acme" / "2026-10-05" / "run.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["entries"][0]["likely_bidders"] = [
        {
            "name": f"Bidder {SCRIPT}",
            "country": "GB",
            "wins": 2,
            "last_won": "2026-09-01",
            "source_url": "https://example.test/award",
            "quote": "Awarded to Bidder",
        }
    ]
    path.write_text(json.dumps(raw), encoding="utf-8")
    app.dependency_overrides[reports] = lambda: folder
    yield folder
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def client(base: Path) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


def feedback_body(**over) -> dict:
    body = {
        "client": "acme",
        "as_of": "2026-10-05",
        "rank": 1,
        "company": "Invented Buyer 0",
        "correct": True,
        "relevant": True,
        "new": False,
        "actionable": True,
    }
    body.update(over)
    return body


async def test_clients_lists_latest_run(client: AsyncClient) -> None:
    rows = (await client.get("/api/clients")).json()
    assert [r["client_id"] for r in rows] == ["acme"]
    assert rows[0]["latest"] == "2026-10-05"
    assert rows[0]["tenders"] == 2
    assert rows[0]["accounts"] == 1


async def test_brief_uses_brief_helpers(client: AsyncClient, base: Path) -> None:
    data = (await client.get("/api/clients/acme/runs/latest")).json()
    assert data["as_of"] == "2026-10-05"
    assert {r["status"] for r in data["tenders"]} == {"watch only"}
    row = data["tenders"][0]
    run, _ = store.load_run(base, "acme", "2026-10-05")
    entry = next(e for e in run.entries if e.rank == row["rank"])
    assert row["caution"] == brief.caution(entry)
    assert row["why_now"] == brief._why_now(entry, date(2026, 10, 5))
    assert row["what"] == brief._what(entry.candidate)
    assert data["accounts"][0]["status"] in {"contact now", "qualify first"}


async def test_dossier_has_claims_sources_bidders_and_labels(client: AsyncClient) -> None:
    d = (await client.get("/api/clients/acme/runs/2026-10-05/entries/1")).json()
    assert d["claims"]
    assert d["claims"][0]["quote"]
    assert d["claims"][0]["url"].startswith("https")
    assert d["sources"]
    assert d["demand"]["model_written"] is True
    assert d["likely_bidders"][0]["wins"] == 2
    assert d["decision_line"] == brief.DECISION_LINE
    assert d["stream"] == RadarStream.TENDER.value


async def test_missing_things_are_404(client: AsyncClient) -> None:
    assert (await client.get("/api/clients/acme/runs/2026-10-05/entries/99")).status_code == 404
    assert (await client.get("/api/clients/nobody/runs/latest")).status_code == 404
    assert (await client.get("/api/clients/acme/runs/2026-13-45")).status_code == 404
    assert (await client.get("/api/clients/..%2Fx/runs/latest")).status_code == 404


async def test_untrusted_text_is_returned_as_json_data(client: AsyncClient) -> None:
    resp = await client.get("/api/clients/acme/runs/2026-10-05/entries/3")
    assert resp.headers["content-type"].startswith("application/json")
    # kept verbatim; the page renders it as text, never as HTML
    assert SCRIPT in resp.json()["claims"][0]["quote"]


async def test_feedback_is_appended_not_overwritten(client: AsyncClient, base: Path) -> None:
    first = await client.post("/api/feedback", json=feedback_body())
    second = await client.post(
        "/api/feedback", json=feedback_body(correct=False, failure_chip="wrong fact", note="x\ny")
    )
    assert first.status_code == second.status_code == 201
    path = base.parent / "feedback" / "acme.jsonl"
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["correct"] is True
    assert json.loads(lines[1])["note"] == "x\ny"
    assert "received_at" in json.loads(lines[1])
    got = (await client.get("/api/clients/acme/feedback", params={"as_of": "2026-10-05"})).json()
    assert len(got) == 2


@pytest.mark.parametrize(
    "over",
    [
        {"failure_chip": "made up"},
        {"outcome": "bought a yacht"},
        {"rank": 0},
        {"as_of": "05/10/2026"},
        {"surprise": 1},
        {"note": "n" * 2001},
        {"correct": "maybe"},
    ],
)
async def test_feedback_validation(client: AsyncClient, base: Path, over: dict) -> None:
    resp = await client.post("/api/feedback", json=feedback_body(**over))
    assert resp.status_code == 422
    assert not (base.parent / "feedback").exists()


async def test_feedback_for_unknown_entry_or_client(client: AsyncClient, base: Path) -> None:
    assert (await client.post("/api/feedback", json=feedback_body(rank=99))).status_code == 404
    bad = await client.post("/api/feedback", json=feedback_body(client="../x"))
    assert bad.status_code == 404
    assert not (base.parent / "feedback").exists()
