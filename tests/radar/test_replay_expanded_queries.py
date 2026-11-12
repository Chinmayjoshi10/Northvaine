"""A recording that stores the expanded query set (D126+) replays; a changed spec is refused."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

from northvaine.core.settings import Settings
from northvaine.radar.models import ClientSpec
from northvaine.radar.run import expanded_queries, with_target_accounts
from northvaine.sensors.base import SensorQuery

ROOT = Path(__file__).resolve().parents[2]
SPEC = ClientSpec(
    id="widget_maker",
    offer="Industrial widgets for factories.",
    markets=["GB", "FR"],
    sensors={},
    offer_terms=["widgets"],
    buyer_roles=["factories", "distributors"],
    need_triggers=["new factory", "plant expansion"],
)
SETTINGS = Settings(_env_file=None)


def _script() -> Any:
    spec = importlib.util.spec_from_file_location("nv_radar_script_exp", ROOT / "scripts/radar.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _expanded(_client: str) -> tuple[Any, Any, dict[str, list[SensorQuery]]]:
    from datetime import UTC, datetime

    spec = SPEC
    as_of = datetime(2026, 10, 1, tzinfo=UTC)
    queries, _, _ = expanded_queries(spec, as_of, SETTINGS)
    queries, _, _ = with_target_accounts(spec, queries, SETTINGS)
    return spec, as_of, queries


def test_a_recording_of_the_expanded_set_matches() -> None:
    spec, as_of, queries = _expanded("polypipe_com")
    assert _script().queries_match(spec, as_of, SETTINGS, queries)


def test_the_expanded_set_adds_searches_beyond_the_specs_own() -> None:
    from northvaine.radar.discover import prepare_queries

    spec, as_of, queries = _expanded("polypipe_com")
    plain = prepare_queries(spec.sensors, as_of.date(), SETTINGS)
    assert sum(map(len, queries.values())) > sum(map(len, plain.values()))
    assert _script().queries_match(spec, as_of, SETTINGS, plain)  # older recordings still replay


def test_a_changed_recording_is_refused() -> None:
    spec, as_of, queries = _expanded("polypipe_com")
    changed = {k: list(v) for k, v in queries.items()}
    changed["tavily"] = changed.get("tavily", [])[:-1]
    assert not _script().queries_match(spec, as_of, SETTINGS, changed)
