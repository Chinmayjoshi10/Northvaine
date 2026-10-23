"""CORS: a listed origin gets the header, an unlisted one does not. No network."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from northvaine.api.main import add_cors
from northvaine.core.settings import Settings

PAGES = "https://example.test"


def _app(origins: list[str]) -> TestClient:
    app = FastAPI()
    add_cors(app, origins)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return TestClient(app)


def test_listed_origin_gets_the_header() -> None:
    r = _app([PAGES]).get("/health", headers={"Origin": PAGES})
    assert r.headers["access-control-allow-origin"] == PAGES
    assert "access-control-allow-credentials" not in r.headers


def test_unlisted_origin_does_not() -> None:
    r = _app([PAGES]).get("/health", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in r.headers


def test_default_allows_no_extra_origin() -> None:
    r = _app([]).get("/health", headers={"Origin": PAGES})
    assert "access-control-allow-origin" not in r.headers


def test_setting_reads_a_json_list(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CORS_ORIGINS", f'["{PAGES}"]')
    assert Settings(_env_file=None).cors_origins == [PAGES]
    monkeypatch.delenv("CORS_ORIGINS")
    assert Settings(_env_file=None).cors_origins == []
