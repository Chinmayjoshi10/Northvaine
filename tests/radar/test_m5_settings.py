"""M5 radar settings (T5.0): defaults as in PLAN.md and validation of bad values."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from northvaine.core.settings import Settings
from northvaine.radar.models import RadarStream

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture
def s(clean_settings: None) -> Settings:
    return Settings(_env_file=None)


def test_defaults(s: Settings) -> None:
    assert s.radar_clients_dir == "tests/fixtures/clients"
    assert s.radar_reports_dir == "reports/radar"
    assert s.radar_fixtures_dir == "tests/fixtures/radar"
    assert s.radar_max_lead_upgrades == 15
    assert s.radar_max_gate_candidates == 40
    assert s.radar_brief_entries == 10
    assert s.radar_tender_window_days == 30
    assert s.radar_recent_days == 90
    assert s.radar_stream_by_event == {
        "tender_published": "tender",
        "contract_awarded": "award",
        "imports_recorded": "trade",
    }
    assert s.radar_enumerable_sources == ("ted", "fts", "worldbank", "usaspending", "hmrc")
    assert s.gate_max_tokens == 700
    assert s.skeptic_max_tokens == 600
    assert s.radar_run_budget_usd == Decimal("1.00")


def test_legal_forms_are_lowercase_tokens(s: Settings) -> None:
    assert {"ltd", "gmbh", "sp z o o", "plc"} <= set(s.radar_legal_forms)
    assert all(f == f.lower() and f.strip() == f for f in s.radar_legal_forms)


def test_default_stream_map_values_are_radar_streams(s: Settings) -> None:
    valid = {x.value for x in RadarStream}
    assert set(s.radar_stream_by_event.values()) <= valid


@pytest.mark.parametrize(
    "field",
    [
        "radar_max_lead_upgrades",
        "radar_max_gate_candidates",
        "radar_brief_entries",
        "radar_tender_window_days",
        "radar_recent_days",
        "gate_max_tokens",
        "skeptic_max_tokens",
    ],
)
@pytest.mark.parametrize("bad", [0, -1])
def test_positive_ints_are_enforced(clean_settings: None, field: str, bad: int) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **{field: bad})


@pytest.mark.parametrize("bad", [Decimal("0"), Decimal("-1")])
def test_run_budget_must_be_positive(clean_settings: None, bad: Decimal) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, radar_run_budget_usd=bad)


def test_stream_map_values_must_be_radar_streams(clean_settings: None) -> None:
    with pytest.raises(ValidationError, match="tender, award, announcement or trade"):
        Settings(_env_file=None, radar_stream_by_event={"tender_published": "bogus"})
    ok = Settings(_env_file=None, radar_stream_by_event={"x_event": "announcement"})
    assert ok.radar_stream_by_event == {"x_event": "announcement"}


def test_enumerable_sources_must_not_be_empty(clean_settings: None) -> None:
    with pytest.raises(ValidationError, match="must not be empty"):
        Settings(_env_file=None, radar_enumerable_sources=())


def test_settings_data_has_no_industry_words(s: Settings) -> None:
    lines = (REPO / "factory" / "banned_terms.txt").read_text(encoding="utf-8").splitlines()
    terms = {ln.strip().lower() for ln in lines if ln.strip() and not ln.startswith("#")}
    blob = json.dumps(
        [
            s.radar_stream_by_event,
            list(s.radar_enumerable_sources),
            list(s.radar_legal_forms),
            s.radar_clients_dir,
            s.radar_reports_dir,
            s.radar_fixtures_dir,
        ]
    ).lower()
    words = set(blob.replace('"', " ").replace("_", " ").replace("/", " ").split())
    assert not words & terms
