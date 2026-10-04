"""Generality (D33): one code path serves every sample client, and no client value is
hardcoded in the package (T3.6). No network."""

from __future__ import annotations

import ast
import json
from datetime import timedelta
from pathlib import Path

import httpx
import pytest
from pydantic import SecretStr

from northvaine.core.settings import Settings
from northvaine.sensors.base import SensorQuery
from northvaine.sensors.registry import get_sensor
from northvaine.sensors.replay import load_exchanges, replay_transport

ROOT = Path(__file__).parent.parent
CLIENTS = ROOT / "fixtures" / "clients"
RECORDED = ROOT / "fixtures" / "sensors"
PACKAGE = ROOT.parent / "northvaine"
SETTINGS = Settings(_env_file=None, ted_min_interval_seconds=0, tavily_api_key=SecretStr("k"))
CLIENT_FILES = sorted(CLIENTS.glob("*.json"))


def load_spec(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def recorded_bodies(sensor: str, client_id: str) -> list:
    exchanges = []
    for path in sorted((RECORDED / sensor).glob(f"{client_id}_*.json")):
        exchanges.extend(load_exchanges(path))
    return exchanges


def test_there_are_several_very_different_clients() -> None:
    assert len(CLIENT_FILES) >= 3


@pytest.mark.parametrize("path", CLIENT_FILES, ids=lambda p: p.stem)
async def test_same_loop_serves_every_client(path: Path) -> None:
    spec = load_spec(path)
    for name, queries in spec["sensors"].items():
        if not queries:
            continue
        exchanges = recorded_bodies(name, spec["id"])
        sent = {json.dumps(e.request_json, sort_keys=True) for e in exchanges}
        documents = []
        for raw in queries:
            query = SensorQuery.model_validate(raw)
            # The recorder refused some Tavily responses (PII); only recorded calls replay.
            probe = httpx.AsyncClient(transport=replay_transport(exchanges))
            async with probe as replay_client:
                sensor = get_sensor(name, client=replay_client, settings=SETTINGS)
                if not _is_recorded(name, query, sent):
                    continue
                result = await sensor.search(query)
            documents.extend(result.documents)
        assert len(documents) >= 1, f"{spec['id']} / {name} produced no documents"
        for doc in documents:
            assert doc.content_hash
            assert doc.fetched_at.tzinfo is not None
            if name == "ted":
                assert doc.available_at is not None
                assert doc.group_key
            if name == "tavily":
                assert doc.available_at == doc.fetched_at
                assert doc.fetched_at.utcoffset() == timedelta(0)


def _is_recorded(name: str, query: SensorQuery, sent: set[str]) -> bool:
    from northvaine.sensors import tavily, ted

    if name == "ted":
        body = ted.build_request(query, settings=SETTINGS)
    else:
        body, _ = tavily.build_search_request(query, settings=SETTINGS)
    return json.dumps(body, sort_keys=True) in sent


# ------------------------------------------------------------------ no client value in code

# Excluded from the check, by design: ISO 3166 country codes and ISO 639-1 language codes
# (generic standards, not client knowledge) and any single word (generic vocabulary). Only full
# CPV codes (with or without the 'cpv:' prefix) and whole multi-word query texts are searched.


def client_values() -> set[str]:
    values: set[str] = set()
    for path in CLIENT_FILES:
        spec = load_spec(path)
        for queries in spec["sensors"].values():
            for q in queries:
                for code in q.get("codes", []):
                    values.add(code)
                    values.add(code.split(":", 1)[-1])
                text = q.get("text")
                if text and len(text.split()) > 1:
                    values.add(text)
    return values


def string_constants(source: str) -> set[str]:
    return {
        node.value
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }


def test_client_values_were_collected() -> None:
    values = client_values()
    assert any(v.startswith("cpv:") for v in values)
    assert any(" " in v for v in values)


def test_no_client_value_is_a_string_constant_in_the_package() -> None:
    values = {v.casefold() for v in client_values()}
    offences = []
    for path in sorted(PACKAGE.rglob("*.py")):
        for const in string_constants(path.read_text(encoding="utf-8")):
            if const.casefold().strip() in values:
                offences.append(f"{path.relative_to(PACKAGE.parent)}: {const!r}")
    assert not offences, offences


def test_the_ast_check_catches_a_planted_constant() -> None:
    planted = 'CODES = ["cpv:44113120"]\nX = "44113120"\n'
    assert {"cpv:44113120", "44113120"} <= string_constants(planted)
    assert "44113120" in {v for v in client_values()}
