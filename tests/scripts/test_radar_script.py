"""T5.6: scripts/radar.py. Replay needs no `.env` and no network; record needs `--yes`.

The round trip test records with a scripted model and replayed sensor fixtures standing in for the
live APIs, then replays the recording it wrote and checks the brief is byte-identical. Nothing
here touches the network (every HTTP path is a mock transport or a spy that fails the test).
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from types import ModuleType
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from northvaine.brain import llm
from northvaine.brain.replay import normalize_body
from northvaine.core.settings import Settings
from northvaine.radar.discover import RecordedPageFetcher
from northvaine.sensors.replay import replay_transport
from tests.radar.test_run import MODEL_FAST, MODEL_MID, FakeLlm, recorded_world

REPO = Path(__file__).resolve().parents[2]
EMBED_MODEL = "Qwen/Qwen3-Embedding-8B"
TAVILY_KEY = "replay-only-0123456789"


def load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("nv_radar_script", REPO / "scripts" / "radar.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def radar(clean_settings: None) -> ModuleType:
    return load_script()


@pytest.fixture
def no_network(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Spies: any real HTTP send, model client or recording run fails the test."""
    calls: list[str] = []

    async def no_send(self: Any, request: Any) -> Any:
        calls.append(f"http {request.url}")
        raise AssertionError(f"network call to {request.url}")

    def no_client() -> Any:
        calls.append("llm client")
        raise AssertionError("a model client was built")

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", no_send)
    monkeypatch.setattr(llm, "get_client", no_client)
    return calls


def record_settings(**extra: Any) -> Settings:
    values: dict[str, Any] = {
        "ted_min_interval_seconds": 0,
        "tavily_api_key": SecretStr(TAVILY_KEY),
        "daily_budget_usd": "10",
        "total_budget_usd": "29",
        "model_fast": MODEL_FAST,
        "model_mid": MODEL_MID,
        "model_embed": EMBED_MODEL,
        # The M3 recordings hold one page of 10; replay must reuse this recorded value (D71).
        "radar_enumerable_max_results": 10,
        "radar_bidder_max_queries": 0,  # no award searches in the M3 recordings (D81)
        "radar_fit_max_accounts": 0,  # nor company-fit searches (D96)
    }
    values.update(extra)
    return Settings(_env_file=None, **values)


# --- replay ---------------------------------------------------------------------------------


def test_replay_with_a_missing_recording_exits_2_and_says_how_to_record(
    radar: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str], no_network: list[str]
) -> None:
    code = radar.main(
        ["--client", "stone_supplier", "--fixtures-dir", str(tmp_path), "--out", str(tmp_path)]
    )
    assert code == 2
    err = capsys.readouterr().err
    assert "record it with" in err.lower() and "record-radar" in err
    assert "stone_supplier" in err
    assert no_network == []
    assert not (tmp_path / "stone_supplier").exists()


def test_an_unknown_client_exits_2(
    radar: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert radar.main(["--client", "no_such_client", "--fixtures-dir", str(tmp_path)]) == 2
    assert "no_such_client" in capsys.readouterr().err


def test_client_is_required(radar: ModuleType) -> None:
    with pytest.raises(SystemExit) as exc:
        radar.main([])
    assert exc.value.code == 2


@pytest.mark.parametrize("flags", [["--yes"], ["--as-of", "2026-10-05"]])
def test_record_only_flags_are_refused_in_replay(
    radar: ModuleType, flags: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    assert radar.main(["--client", "stone_supplier", *flags]) == 2
    assert "--record" in capsys.readouterr().err


# --- record ---------------------------------------------------------------------------------


def test_record_without_yes_prints_a_plan_and_calls_nothing(
    radar: ModuleType,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    no_network: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def never(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("the pipeline ran without --yes")

    monkeypatch.setattr(radar, "run_record", never)
    code = radar.main(
        ["--client", "stone_supplier", "--record", "--fixtures-dir", str(tmp_path)],
        settings=record_settings(),
    )
    captured = capsys.readouterr()
    assert code == 1
    assert "plan" in captured.out.lower()
    assert "Tavily credits" in captured.out and "gate" in captured.out
    assert "--yes" in captured.err
    assert no_network == []
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    ("missing", "settings"),
    [
        ("DAILY_BUDGET_USD", record_settings(daily_budget_usd=None)),
        ("TOTAL_BUDGET_USD", record_settings(total_budget_usd=None)),
        ("MODEL_MID", record_settings(model_mid=None)),
    ],
)
def test_record_refuses_without_budget_caps_or_models(
    radar: ModuleType,
    missing: str,
    settings: Settings,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    no_network: list[str],
) -> None:
    code = radar.main(
        ["--client", "stone_supplier", "--record", "--yes", "--fixtures-dir", str(tmp_path)],
        settings=settings,
    )
    assert code == 2
    assert missing in capsys.readouterr().err
    assert no_network == []
    assert list(tmp_path.iterdir()) == []


# --- the round trip -------------------------------------------------------------------------


class ScriptedLlm(FakeLlm):
    """Answers vary by request but are fixed for a given request (a replay needs that)."""

    async def _create(self, **body: Any) -> Any:
        text = json.dumps(normalize_body(body)["messages"], sort_keys=True)
        self.key = hashlib.sha256(text.encode()).hexdigest()
        return await super()._create(**body)


def write_spec(clients_dir: Path, client_id: str) -> tuple[Any, list[Any], list[Any]]:
    """A client spec cut to the recorded queries, written where `--clients-dir` can read it."""
    spec, exchanges, pages = recorded_world(client_id)
    clients_dir.mkdir()
    (clients_dir / f"{client_id}.json").write_text(
        json.dumps(spec.model_dump(mode="json")), encoding="utf-8"
    )
    return spec, exchanges, pages


@asynccontextmanager
async def no_session() -> AsyncIterator[None]:
    """A stand-in for session_scope: the round trip writes no llm_calls rows."""
    yield None


def test_record_then_replay_gives_the_same_brief_with_no_network(
    radar: ModuleType,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MODEL_FAST", MODEL_FAST)
    monkeypatch.setenv("MODEL_MID", MODEL_MID)
    monkeypatch.setenv("MODEL_EMBED", EMBED_MODEL)
    monkeypatch.setenv("DAILY_BUDGET_USD", "10")
    monkeypatch.setenv("TOTAL_BUDGET_USD", "29")
    llm.get_settings.cache_clear()
    client_id = "stone_supplier"
    clients_dir, fixtures, live_out, replay_out = (
        tmp_path / n for n in ("clients", "fixtures", "live", "replay")
    )
    _, exchanges, pages = write_spec(clients_dir, client_id)
    common = ["--client", client_id, "--clients-dir", str(clients_dir)]

    code = radar.main(
        [
            *common,
            *["--record", "--yes", "--as-of", "2026-10-05"],
            *["--fixtures-dir", str(fixtures), "--out", str(live_out)],
        ],
        settings=record_settings(),
        inner_transport=replay_transport(exchanges, match_body=False),
        client_factory=ScriptedLlm,
        fetcher_factory=lambda settings: RecordedPageFetcher(pages),
        session_factory=no_session,
    )
    out = capsys.readouterr().out
    assert code == 0, out
    folder = fixtures / client_id
    assert sorted(p.name for p in folder.iterdir()) == [
        "http.json",
        "llm.json",
        "meta.json",
        "pages.json",
    ]
    meta = json.loads((folder / "meta.json").read_text(encoding="utf-8"))
    assert meta["client"] == client_id and meta["as_of"].startswith("2026-10-05")
    recorded_llm = json.loads((folder / "llm.json").read_text(encoding="utf-8"))
    assert recorded_llm["models"]["mid"] == MODEL_MID
    assert {"gate_max_tokens", "skeptic_max_tokens"} <= set(recorded_llm["settings"])
    assert TAVILY_KEY not in "".join(p.read_text(encoding="utf-8") for p in folder.iterdir())
    for stage in ("documents:", "leads:", "upgraded:", "candidates:", "rejected:", "briefed:"):
        assert stage in out

    # replay: nothing live may be reachable
    def refuse(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("replay reached for the network or the model")

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", refuse)
    monkeypatch.setattr(llm, "_cached_client", refuse)
    for name in ("MODEL_FAST", "MODEL_MID", "MODEL_EMBED", "DAILY_BUDGET_USD", "TOTAL_BUDGET_USD"):
        monkeypatch.delenv(name)
    llm.get_settings.cache_clear()
    first = radar.main([*common, "--fixtures-dir", str(fixtures), "--out", str(replay_out)])
    assert first == 0
    second = radar.main([*common, "--fixtures-dir", str(fixtures), "--out", str(replay_out)])
    assert second == 0

    live = live_out / client_id / "2026-10-05"
    replayed = replay_out / client_id / "2026-10-05"
    for name in ("brief.md", "scorecard.md", "run.json"):
        assert (replayed / name).read_bytes() == (live / name).read_bytes(), name
    assert b"\r" not in (replayed / "brief.md").read_bytes()
    run_json = json.loads((replayed / "run.json").read_text(encoding="utf-8"))
    assert run_json["entries"] and run_json["rejected"]


def test_record_refuses_to_write_when_a_phone_number_survives(
    radar: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    recording = radar.Recording(
        meta=radar.RadarMeta(client="c", as_of="2026-10-05T00:00:00Z", recorded_at="x", queries={}),
        exchanges=[],
        pages=[
            radar.UpgradedPage(
                lead_url="https://example.test/a",
                final_url=None,
                status=200,
                fetched_at=None,
                title=None,
                text="Call +33 1 23 45 67 89 now",
                refused=None,
            )
        ],
        llm=radar.LlmRecording(recorded_at="x", models={}, settings={}, exchanges=[]),
    )
    with pytest.raises(radar.Refused) as exc:
        radar.redact_recording(recording, record_settings())
    assert "email or phone" in str(exc.value)


def test_search_result_contacts_are_stripped_the_way_the_pipeline_strips_them(
    radar: ModuleType,
) -> None:
    from northvaine.radar.discover import strip_contacts
    from northvaine.sensors.replay import RecordedExchange

    raw = "Call +44 20 7946 0000 or write to " + "sales" + "@" + "example.org today."
    ex = RecordedExchange.model_validate(
        {
            "method": "POST",
            "url": "https://api.tavily.com/search",
            "request_json": {"query": "q"},
            "status": 200,
            "body_json": {"results": [{"url": "https://x.test", "raw_content": raw, "score": 1}]},
            "recorded_at": "2026-10-05T00:00:00+00:00",
        }
    )
    out = radar._strip_search_contacts(ex, "https://api.tavily.com")
    kept = out.body_json["results"][0]
    assert kept["raw_content"] == strip_contacts(raw)
    assert strip_contacts(kept["raw_content"]) == kept["raw_content"]  # idempotent: replay = live
    assert "example.org" not in kept["raw_content"] and kept["score"] == 1


def test_fts_free_text_and_contacts_are_dropped_and_the_parse_is_unchanged(
    radar: ModuleType,
) -> None:
    from datetime import UTC, datetime

    from northvaine.sensors.fts import FTS_API_URL, parse_release
    from northvaine.sensors.replay import RecordedExchange

    mail = "bids" + "@" + "example.org"
    release = {
        "ocid": "ocds-test-1",
        "id": "000001-2026",
        "tag": ["tender"],
        "date": "2026-06-01T10:00:00+01:00",
        "language": "en",
        "buyer": {"id": "B1", "name": "Example Council"},
        "parties": [
            {
                "id": "B1",
                "name": "Example Council",
                "address": {"streetAddress": "1 Example Road", "country": "GB"},
                "contactPoint": {"email": mail, "telephone": "+44 20 7946 0000"},
            }
        ],
        "planning": {"milestones": [{"description": f"write to {mail}"}]},
        "tender": {
            "title": "Wall tiling, enquiries 020 7946 0000",
            "description": f"Questions to {mail}",
            "submissionMethodDetails": "Call +44 20 7946 0000",
            "lots": [
                {"description": f"Lot 1, {mail}", "value": {"amount": 1000, "currency": "GBP"}}
            ],
        },
    }
    ex = RecordedExchange.model_validate(
        {
            "method": "GET",
            "url": FTS_API_URL + "?limit=100",
            "status": 200,
            "body_json": {"releases": [release]},
            "recorded_at": "2026-10-15T00:00:00Z",
        }
    )
    cleaned = radar._strip_fts_unread(ex)
    dumped = json.dumps(cleaned.body_json)
    assert "example.org" not in dumped and "7946" not in dumped and "Example Road" not in dumped
    fetched = datetime(2026, 10, 15, tzinfo=UTC)
    kept = cleaned.body_json["releases"][0]
    assert (
        parse_release(kept, fetched_at=fetched).text
        == parse_release(release, fetched_at=fetched).text
    )
    assert (
        parse_release(kept, fetched_at=fetched).meta
        == parse_release(release, fetched_at=fetched).meta
    )
