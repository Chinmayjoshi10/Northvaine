"""export_static writes what the app serves, at the paths the frontend asks for. No network."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from fastapi.testclient import TestClient

from northvaine.api.feedback import reports
from northvaine.api.main import app
from northvaine.radar import brief
from tests.radar.test_brief import make_run

REPO = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("nv_export", REPO / "scripts" / "export_static.py")
assert spec and spec.loader
export_static = importlib.util.module_from_spec(spec)
spec.loader.exec_module(export_static)


def _reports(tmp_path: Path) -> Path:
    folder = tmp_path / "reports" / "radar"
    run = make_run(2).model_copy(update={"client_id": "acme"})
    brief.write_reports(run, folder)
    return folder


def test_static_file_paths() -> None:
    f = export_static.static_file
    assert f("/api/clients") == "api/clients.json"
    assert f("/api/clients/a/runs/latest") == "api/clients/a/runs/latest.json"
    assert f("/api/clients/a/runs/2026-10-05/entries/3") == (
        "api/clients/a/runs/2026-10-05/entries/3.json"
    )
    assert f("/api/clients/a/feedback?as_of=2026-10-05") == (
        "api/clients/a/feedback/2026-10-05.json"
    )


def test_export_matches_the_api(tmp_path: Path) -> None:
    base = _reports(tmp_path)
    out = tmp_path / "site"
    written = export_static.export(base, out)
    day = "2026-10-05"
    expected = {
        "api/clients.json",
        "api/clients/acme/learning.json",
        f"api/clients/acme/feedback/{day}.json",
        f"api/clients/acme/runs/{day}.json",
        "api/clients/acme/runs/latest.json",
        f"api/clients/acme/runs/{day}/entries/1.json",
        "api/clients/acme/runs/latest/entries/1.json",
    }
    assert expected <= set(written)  # business is skipped when no spec is on file
    app.dependency_overrides[reports] = lambda: base
    try:
        http = TestClient(app)
        for rel in expected:
            api_path = "/" + rel.removesuffix(".json")
            api_path = api_path.replace(f"/feedback/{day}", f"/feedback?as_of={day}")
            assert json.loads((out / rel).read_text(encoding="utf-8")) == http.get(api_path).json()
    finally:
        app.dependency_overrides.clear()


def test_empty_reports_exit_nonzero(tmp_path: Path) -> None:
    assert export_static.main(["--reports", str(tmp_path), "--out", str(tmp_path / "o")]) == 1
