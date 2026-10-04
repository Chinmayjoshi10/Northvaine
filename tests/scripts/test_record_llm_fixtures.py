"""Offline tests for the LLM fixture recorder (T4.1): a stubbed `build_evidence`, a fake inner
client and no database. The real run is an orchestrator-only step (D53)."""

from __future__ import annotations

import importlib.util
import json
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

from northvaine.brain import llm
from northvaine.brain.replay import ReplayClient, load_recording
from northvaine.core.settings import Settings

REPO = Path(__file__).resolve().parents[2]
FAST = "nvidia/Nemotron-3_5-Lightning"
EMBED = "Qwen/Qwen3-Embedding-8B"
KEY = "-".join(["nvapi", "SYNTHETIC", "0123456789abcdef"])


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "nv_record_llm", REPO / "scripts" / "record_llm_fixtures.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


rec = _load()


def _settings(**kw: Any) -> Settings:
    base: dict[str, Any] = {
        "model_fast": FAST,
        "model_embed": EMBED,
        "daily_budget_usd": "5",
        "total_budget_usd": "29",
        "database_url": "postgresql://u:p@localhost/db",
    }
    base.update(kw)
    return Settings(_env_file=None, **base)


class FakeInner:
    """The real client's stand-in: echoes a canned reply, keeps every request."""

    def __init__(self, content: str = '{"claims":[]}') -> None:
        self.content = content
        self.requests: list[dict[str, Any]] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._chat))
        self.embeddings = SimpleNamespace(create=self._embed)

    async def _chat(self, **body: Any) -> Any:
        self.requests.append(body)
        return SimpleNamespace(
            model=FAST,
            choices=[
                SimpleNamespace(message=SimpleNamespace(content=self.content), finish_reason="stop")
            ],
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=2, total_tokens=12),
        )

    async def _embed(self, **body: Any) -> Any:
        self.requests.append(body)
        return SimpleNamespace(
            model=EMBED,
            data=[SimpleNamespace(embedding=[0.1234567891, 0.5])],
            usage=SimpleNamespace(prompt_tokens=3, total_tokens=3),
        )


class Harness:
    """Everything `main` can be handed, with calls counted."""

    def __init__(self, inner: FakeInner | None = None, head: str = "0005") -> None:
        self.inner = inner or FakeInner()
        self.head_value = head
        self.documents: list[str] = []
        self.client_made = False

    async def head(self, url: str) -> str:
        return self.head_value

    @asynccontextmanager
    async def session(self):  # type: ignore[no-untyped-def]
        yield object()

    async def concepts(self, session: Any) -> list[Any]:
        return []

    async def build_evidence(self, doc: Any, concepts: list[Any], recent: list[Any], **kw: Any):  # type: ignore[no-untyped-def]
        self.documents.append(doc.url)
        client = llm.get_client()  # the recorder, under client_override
        await client.chat.completions.create(
            model=FAST, messages=[{"role": "user", "content": doc.text[:40]}], max_tokens=10
        )
        await client.embeddings.create(model=EMBED, input=doc.title or "t", dimensions=2)

    def factory(self) -> FakeInner:
        self.client_made = True
        return self.inner

    def run(self, argv: list[str], out: Path, **kw: Any) -> int:
        return rec.main(
            argv,
            out_dir=out,
            settings=kw.pop("settings", _settings()),
            head=self.head,
            session_factory=self.session,
            load_concepts=self.concepts,
            build_evidence=self.build_evidence,
            client_factory=self.factory,
            **kw,
        )


# --- plan ---------------------------------------------------------------------------------


def test_without_yes_it_prints_the_plan_and_calls_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    harness = Harness()
    assert harness.run([], tmp_path) == 0
    out = capsys.readouterr().out
    assert "plan" in out and "estimated calls" in out and "cost<=" in out
    for client in ("stone_supplier", "coldchain_maker", "packaging_supplier", "web"):
        assert client in out
    assert harness.documents == []
    assert not harness.client_made
    assert list(tmp_path.iterdir()) == []


def test_plan_works_with_no_models_configured(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bare = Settings(_env_file=None)
    assert Harness().run([], tmp_path, settings=bare) == 0
    assert "unknown" in capsys.readouterr().out


def test_the_real_fixtures_become_documents_and_pass_the_preflight() -> None:
    import asyncio

    groups = asyncio.run(rec.build_groups())
    names = {g.name for g in groups}
    assert {"stone_supplier", "coldchain_maker", "packaging_supplier", "web"} <= names
    by_name = {g.name: g for g in groups}
    assert len(by_name["web"].documents) == 3
    assert all(d.source_name == "website" for d in by_name["web"].documents)
    assert any(g.documents for g in groups if g.name != "web")
    assert rec.preflight(groups, _settings()) == []


# --- refusals -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("settings", "message"),
    [
        (_settings(daily_budget_usd=None), "DAILY_BUDGET_USD"),
        (_settings(total_budget_usd=None), "TOTAL_BUDGET_USD"),
        (_settings(model_fast=None), "MODEL_FAST"),
        (_settings(database_url=None), "DATABASE_URL"),
    ],
)
def test_yes_refuses_without_caps_models_or_database(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], settings: Settings, message: str
) -> None:
    harness = Harness()
    assert harness.run(["--yes"], tmp_path, settings=settings) == 2
    assert message in capsys.readouterr().err
    assert not harness.client_made and harness.documents == []


def test_yes_refuses_when_the_database_is_not_at_0005(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    harness = Harness(head="0004")
    assert harness.run(["--yes"], tmp_path) == 2
    assert "0005" in capsys.readouterr().err
    assert not harness.client_made and harness.documents == []


def test_a_secret_shaped_document_is_refused_before_any_call(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    web = tmp_path / "web"
    web.mkdir()
    (web / "page.html").write_text(f"<p>Our key is {KEY}</p>", encoding="utf-8")
    harness = Harness()
    out = tmp_path / "out"
    code = harness.run(["--yes", "--client", "web"], out, web_dir=web)
    assert code == 2
    assert "REFUSED" in capsys.readouterr().err
    assert not harness.client_made and not out.exists()


# --- a full run ---------------------------------------------------------------------------


def test_a_run_writes_loadable_recordings_that_replay(tmp_path: Path) -> None:
    harness = Harness()
    out = tmp_path / "ledger"
    assert harness.run(["--yes", "--client", "web"], out) == 0
    assert [p.name for p in out.iterdir()] == ["web.json"]
    assert len(harness.documents) == 3
    recording = load_recording(out / "web.json")
    assert recording.models == {"fast": FAST, "embed": EMBED}
    assert set(recording.settings) == set(rec.SHAPING_SETTINGS)
    assert [e.kind for e in recording.exchanges].count("chat") == 3
    embeds = [e for e in recording.exchanges if e.kind == "embed"]
    assert embeds[0].response["data"][0]["embedding"] == [0.123457, 0.5]
    # it is a real recording: the replay client serves a recorded request
    body = recording.exchanges[0].request
    served = ReplayClient(recording).answer("chat", body)
    assert served.choices[0].message.content == '{"claims":[]}'


def test_every_group_gets_a_file(tmp_path: Path) -> None:
    harness = Harness()
    out = tmp_path / "ledger"
    assert harness.run(["--yes"], out) == 0
    names = {p.stem for p in out.iterdir()}
    assert {"stone_supplier", "coldchain_maker", "packaging_supplier", "web"} <= names


def test_an_email_in_a_reply_means_nothing_is_written(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    harness = Harness(FakeInner('{"note":"write to jane.doe@example.com"}'))
    out = tmp_path / "ledger"
    assert harness.run(["--yes", "--client", "web"], out) == 2
    err = capsys.readouterr().err
    assert "email or phone" in err and "jane.doe" not in err
    assert not out.exists()


def test_a_phone_number_in_a_reply_means_nothing_is_written(tmp_path: Path) -> None:
    harness = Harness(FakeInner('{"note":"call +44 20 7946 0958"}'))
    out = tmp_path / "ledger"
    assert harness.run(["--yes", "--client", "web"], out) == 2
    assert not out.exists()


def test_a_known_key_in_a_reply_is_scrubbed_from_the_file(tmp_path: Path) -> None:
    harness = Harness(FakeInner(json.dumps({"note": f"token {KEY}"})))
    out = tmp_path / "ledger"
    assert harness.run(["--yes", "--client", "web"], out) == 0
    text = (out / "web.json").read_text(encoding="utf-8")
    assert KEY not in text
    assert "[REDACTED]" in text
