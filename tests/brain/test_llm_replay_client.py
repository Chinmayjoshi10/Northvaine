"""The record/replay LLM client and the replay environment (T4.1, D53). No network, no database."""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import BaseModel

from northvaine.brain import llm
from northvaine.brain.budget import RunContext
from northvaine.brain.errors import LlmReplayMismatch
from northvaine.brain.fencing import Untrusted
from northvaine.brain.prompts import Prompt
from northvaine.brain.replay import (
    LlmExchange,
    LlmRecording,
    RecordingClient,
    ReplayClient,
    exchange_key,
    load_recording,
    normalize_body,
    replay_environment,
    save_recording,
)
from northvaine.core import settings as settings_module
from northvaine.core.models import ModelTier
from northvaine.core.settings import Settings
from northvaine.core.standards import EMBED_DIM_EXPECTED

FAST = "nvidia/Nemotron-3_5-Lightning"
MID = "nvidia/nemotron-3-super-120b-a12b"
DEEP = "nvidia/Nemotron-3-Ultra-550b-a55b"
EMBED = "Qwen/Qwen3-Embedding-8B"
MODELS = {"fast": FAST, "mid": MID, "deep": DEEP, "embed": EMBED}


class Answer(BaseModel):
    verdict: str
    count: int


def a_prompt() -> Prompt:
    return Prompt(
        name="replay_probe",
        version=1,
        template="Read this and answer. {topic}\n{snippet}",
        untrusted_vars=frozenset({"snippet"}),
    )


def variables(snippet: str = "Bonjour", topic: str = "greeting") -> dict[str, object]:
    return {"topic": topic, "snippet": Untrusted(snippet)}


def chat_response(content: str, model: str = FAST) -> Any:
    return SimpleNamespace(
        model=model,
        choices=[SimpleNamespace(message=SimpleNamespace(content=content), finish_reason="stop")],
        usage=SimpleNamespace(prompt_tokens=120, completion_tokens=12, total_tokens=132),
    )


def embed_response(vector: list[float]) -> Any:
    return SimpleNamespace(
        model=EMBED,
        data=[SimpleNamespace(embedding=vector)],
        usage=SimpleNamespace(prompt_tokens=4, total_tokens=4),
    )


class FakeInner:
    """Stands in for the real SDK client: scripted replies, every request kept."""

    def __init__(self, chats: list[Any], embeds: list[Any] | None = None) -> None:
        self.chats = list(chats)
        self.embeds = list(embeds or [])
        self.requests: list[tuple[str, dict[str, Any]]] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._chat))
        self.embeddings = SimpleNamespace(create=self._embed)

    async def _chat(self, **body: Any) -> Any:
        self.requests.append(("chat", body))
        return self.chats.pop(0)

    async def _embed(self, **body: Any) -> Any:
        self.requests.append(("embed", body))
        return self.embeds.pop(0)


class FakeSession:
    def __init__(self) -> None:
        self.inserts: list[dict[str, Any]] = []

    async def execute(self, statement: Any, parameters: Any = None, /) -> Any:
        if str(statement).lstrip().startswith("INSERT"):
            self.inserts.append(dict(parameters or {}))
        return SimpleNamespace(scalar_one=lambda: Decimal("0"))


def request_body(prompt: Prompt, vars_: dict[str, object], **kw: Any) -> dict[str, Any]:
    return llm.build_request(
        model=kw.pop("model", FAST),
        rendered=prompt.render(**vars_),
        max_tokens=kw.pop("max_tokens", 300),
        reasoning_effort="none",
        output_model=Answer,
    )


# --- keys ---------------------------------------------------------------------------------


def test_nonces_are_replaced_so_two_renders_share_a_key() -> None:
    prompt = a_prompt()
    first = request_body(prompt, variables())
    second = request_body(prompt, variables())
    assert first["messages"][0]["content"] != second["messages"][0]["content"]  # random nonces
    assert "<NONCE>" in normalize_body(first)["messages"][0]["content"]
    assert exchange_key("chat", first) == exchange_key("chat", second)


def test_normalize_body_leaves_the_original_untouched_and_other_text_alone() -> None:
    body = request_body(a_prompt(), variables("hello"))
    before = json.dumps(body, sort_keys=True)
    normalized = normalize_body(body)
    assert json.dumps(body, sort_keys=True) == before
    assert "hello" in normalized["messages"][0]["content"]
    assert normalized["model"] == FAST


@pytest.mark.parametrize(
    "change",
    [
        {"snippet": "Bonjoux"},
        {"topic": "greetinG"},
        {"max_tokens": 301},
        {"model": MID},
    ],
)
def test_a_one_character_change_changes_the_key(change: dict[str, Any]) -> None:
    prompt = a_prompt()
    base = exchange_key("chat", request_body(prompt, variables()))
    vars_ = variables(change.get("snippet", "Bonjour"), change.get("topic", "greeting"))
    other = request_body(
        prompt,
        vars_,
        **{k: v for k, v in change.items() if k in {"max_tokens", "model"}},
    )
    assert exchange_key("chat", other) != base


def test_kind_is_part_of_the_key_and_key_order_is_not() -> None:
    body = {"model": EMBED, "input": "x", "dimensions": 8}
    assert exchange_key("chat", body) != exchange_key("embed", body)
    assert exchange_key("embed", body) == exchange_key("embed", dict(reversed(body.items())))


# --- recording ----------------------------------------------------------------------------


async def test_recording_client_forwards_and_keeps_pairs() -> None:
    inner = FakeInner(
        [chat_response('{"verdict":"ok","count":1}')], [embed_response([0.12345678, 1.0])]
    )
    client = RecordingClient(inner)
    body = request_body(a_prompt(), variables())
    reply = await client.chat.completions.create(**body)
    vec = await client.embeddings.create(model=EMBED, input="abc", dimensions=2)
    assert reply.choices[0].message.content == '{"verdict":"ok","count":1}'
    assert vec.data[0].embedding == [0.12345678, 1.0]
    assert [kind for kind, _ in inner.requests] == ["chat", "embed"]

    recording = client.recording(models=MODELS, settings={"extract_max_tokens": 300})
    assert [e.kind for e in recording.exchanges] == ["chat", "embed"]
    chat, embed = recording.exchanges
    assert chat.key == exchange_key("chat", body)
    assert "<NONCE>" in chat.request["messages"][0]["content"]
    assert chat.response["choices"][0]["message"]["content"] == '{"verdict":"ok","count":1}'
    assert chat.response["usage"] == {
        "prompt_tokens": 120,
        "completion_tokens": 12,
        "total_tokens": 132,
    }
    assert embed.response["data"][0]["embedding"] == [0.123457, 1.0]
    assert recording.models == MODELS
    assert recording.settings == {"extract_max_tokens": 300}


async def test_save_then_load_round_trips(tmp_path: Path) -> None:
    inner = FakeInner([chat_response("{}")], [embed_response([0.1234567891, -2.0000004])])
    client = RecordingClient(inner)
    await client.chat.completions.create(**request_body(a_prompt(), variables()))
    await client.embeddings.create(model=EMBED, input="abc", dimensions=2)
    recording = client.recording(models=MODELS, settings={})
    path = tmp_path / "sub" / "r.json"
    save_recording(path, recording)
    assert load_recording(path) == recording
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert on_disk["exchanges"][1]["response"]["data"][0]["embedding"] == [0.123457, -2.0]


def test_save_rounds_vectors_even_when_the_recording_was_built_by_hand(tmp_path: Path) -> None:
    exchange = LlmExchange(
        kind="embed",
        key="k",
        request={"model": EMBED},
        response={"data": [{"embedding": [0.1234567891]}]},
    )
    path = tmp_path / "r.json"
    save_recording(path, LlmRecording(recorded_at="t", models={}, exchanges=[exchange]))
    assert load_recording(path).exchanges[0].response["data"][0]["embedding"] == [0.123457]


# --- replay -------------------------------------------------------------------------------


async def recorded(
    chat_content: str = '{"verdict":"ok","count":2}', vector: list[float] | None = None
) -> LlmRecording:
    inner = FakeInner([chat_response(chat_content)], [embed_response(vector or [0.5] * 4)])
    client = RecordingClient(inner)
    await client.chat.completions.create(**request_body(a_prompt(), variables()))
    await client.embeddings.create(model=EMBED, input="abc", dimensions=4)
    return client.recording(models=MODELS, settings={})


async def test_replay_answers_in_the_attribute_shape_llm_reads() -> None:
    client = ReplayClient(await recorded())
    reply = await client.chat.completions.create(**request_body(a_prompt(), variables()))
    assert reply.choices[0].message.content == '{"verdict":"ok","count":2}'
    assert reply.choices[0].finish_reason == "stop"
    assert (reply.usage.prompt_tokens, reply.usage.completion_tokens) == (120, 12)
    vec = await client.embeddings.create(model=EMBED, input="abc", dimensions=4)
    assert vec.data[0].embedding == [0.5] * 4


async def test_a_miss_raises_naming_the_key_and_never_touches_the_network() -> None:
    client = ReplayClient(await recorded())
    body = request_body(a_prompt(), variables("a different snippet"))
    with pytest.raises(LlmReplayMismatch) as caught:
        await client.chat.completions.create(**body)
    assert exchange_key("chat", body) in str(caught.value)
    assert "re-record" in str(caught.value)
    with pytest.raises(LlmReplayMismatch):
        await client.embeddings.create(model=EMBED, input="other", dimensions=4)


async def test_a_miss_names_the_prompt_version_from_front_matter() -> None:
    client = ReplayClient(LlmRecording(recorded_at="t", models={}))
    body = {
        "model": FAST,
        "max_tokens": 5,
        "messages": [
            {"role": "user", "content": "---\nname: evidence_extract\nversion: 1\n---\nx"}
        ],
    }
    with pytest.raises(LlmReplayMismatch, match=r"evidence_extract\.v1"):
        await client.chat.completions.create(**body)


def test_replay_mismatch_is_an_assertion_error() -> None:
    assert issubclass(LlmReplayMismatch, AssertionError)


# --- replay_environment -------------------------------------------------------------------


def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in Settings.model_fields:
        monkeypatch.delenv(name.upper(), raising=False)


@pytest.fixture
def real_settings(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[Path]:
    """The real `get_settings` with cwd in an empty tmp dir, then restored."""
    _clean_env(monkeypatch)
    monkeypatch.chdir(tmp_path)
    settings_module.get_settings.cache_clear()
    yield tmp_path
    settings_module.get_settings.cache_clear()


def test_environment_pins_models_and_caps_and_restores(
    real_settings: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MODEL_FAST", "other/fast")
    monkeypatch.setenv("MODEL_DEEP", "other/deep")
    recording = LlmRecording(
        recorded_at="t", models={"fast": FAST, "embed": EMBED}, settings={"extract_max_tokens": 77}
    )
    with replay_environment(recording):
        settings = settings_module.get_settings()
        assert settings.model_fast == FAST
        assert settings.model_embed == EMBED
        assert settings.model_deep == "other/deep"  # unset tier left alone
        assert settings.model_mid is None
        assert settings.extract_max_tokens == 77
        for cap in (
            settings.daily_budget_usd,
            settings.total_budget_usd,
            settings.run_budget_usd,
            settings.max_call_cost_usd,
        ):
            assert cap is not None and cap >= Decimal("100")
    after = settings_module.get_settings()
    assert after.model_fast == "other/fast"
    assert after.model_embed is None
    assert after.daily_budget_usd is None
    assert "EXTRACT_MAX_TOKENS" not in os.environ


def test_environment_is_restored_after_an_exception(real_settings: Path) -> None:
    with (
        pytest.raises(RuntimeError),
        replay_environment(LlmRecording(recorded_at="t", models=MODELS)),
    ):
        assert settings_module.get_settings().model_fast == FAST
        raise RuntimeError("boom")
    assert settings_module.get_settings().model_fast is None
    assert "MODEL_FAST" not in os.environ


async def test_replay_passes_with_no_dotenv_and_a_different_model_in_the_environment(
    real_settings: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # a stale .env in cwd and a different MODEL_FAST in the process environment
    (real_settings / ".env").write_text("MODEL_FAST=stale/from-dotenv\n", encoding="utf-8")
    monkeypatch.setenv("MODEL_FAST", "other/fast")
    monkeypatch.delenv("NEBIUS_API_KEY", raising=False)
    monkeypatch.delenv("NEBIUS_BASE_URL", raising=False)
    recording = await recorded()
    session = FakeSession()
    with replay_environment(recording), llm.client_override(ReplayClient(recording)):
        result = await llm.complete_json(
            tier=ModelTier.FAST,
            prompt=a_prompt(),
            variables=variables(),
            output_model=Answer,
            purpose="replay-test",
            run=RunContext(),
            session=session,
            max_tokens=300,
        )
    assert result.value == Answer(verdict="ok", count=2)
    assert result.model == FAST
    assert len(session.inserts) == 1


# --- through llm.py -----------------------------------------------------------------------


async def test_complete_json_retries_are_recorded_and_replayed_by_key(
    clean_settings: None,
) -> None:
    run = RunContext()
    prompt = a_prompt()
    inner = FakeInner(
        [chat_response("not json"), chat_response('{"verdict":"fixed","count":3}')],
        [embed_response([0.25] * EMBED_DIM_EXPECTED)],
    )
    recorder = RecordingClient(inner)
    pins = LlmRecording(recorded_at="t", models=MODELS)
    live_session = FakeSession()
    with replay_environment(pins), llm.client_override(recorder):
        first = await llm.complete_json(
            tier=ModelTier.FAST,
            prompt=prompt,
            variables=variables(),
            output_model=Answer,
            purpose="t",
            run=run,
            session=live_session,
            max_tokens=300,
        )
        await llm.embed(text="some text", purpose="t", run=run, session=live_session)
    assert first.value.verdict == "fixed"
    assert len(live_session.inserts) == 3  # two attempts and one embed
    recording = recorder.recording(models=MODELS, settings={})
    assert [e.kind for e in recording.exchanges] == ["chat", "chat", "embed"]

    session = FakeSession()
    replayer = ReplayClient(recording)
    with replay_environment(recording), llm.client_override(replayer):
        again = await llm.complete_json(
            tier=ModelTier.FAST,
            prompt=prompt,
            variables=variables(),
            output_model=Answer,
            purpose="t",
            run=RunContext(),
            session=session,
            max_tokens=300,
        )
        vector = await llm.embed(text="some text", purpose="t", run=RunContext(), session=session)
        assert again.value == first.value
        assert vector.value == [0.25] * EMBED_DIM_EXPECTED
        assert len(session.inserts) == 3  # one llm_calls row per attempt, replay or not

        with pytest.raises(LlmReplayMismatch):
            await llm.complete_json(
                tier=ModelTier.FAST,
                prompt=prompt,
                variables=variables("a planted miss"),
                output_model=Answer,
                purpose="t",
                run=RunContext(),
                session=session,
                max_tokens=300,
            )
        with pytest.raises(LlmReplayMismatch):
            await llm.embed(text="unrecorded text", purpose="t", run=RunContext(), session=session)
