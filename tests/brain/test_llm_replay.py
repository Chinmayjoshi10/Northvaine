"""Replay the recorded fixtures through a fake transport: no network, no database (T2.5b).

Every payload here was recorded from the live API on 3 Oct 2026 by
`scripts/smoke_llm.py`, not hand-written. That ordering is the point of the T2.5 split: a
fixture invented from documentation encodes a guess about the response shape, and the tests
replaying it then pass against a shape the API never produces.

**No fixture is edited to make a test pass.** If a recorded payload contradicts `brain/llm.py`,
that is a finding about the code, not a reason to rewrite the recording.

These run in the default gate: not marked `live`, not marked `db`.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import openai
import pytest
from pydantic import BaseModel

from northvaine.brain import llm as llm_module
from northvaine.brain import pricing
from northvaine.brain.budget import RunContext
from northvaine.brain.fencing import Untrusted
from northvaine.brain.prompts import Prompt
from northvaine.core.models import ModelTier
from northvaine.core.settings import ConfigError, Settings
from northvaine.core.standards import EMBED_DIM_EXPECTED

FIXTURES = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "llm"

FAST = "nvidia/Nemotron-3_5-Lightning"
MID = "nvidia/nemotron-3-super-120b-a12b"
DEEP = "nvidia/Nemotron-3-Ultra-550b-a55b"
EMBED = "Qwen/Qwen3-Embedding-8B"


def load(name: str, *required: str) -> dict[str, Any]:
    """Read a fixture, failing loudly if it is missing or off-schema.

    Deliberately not a skip: a replay suite that quietly skips itself when the recordings go
    missing is how this coverage rots without anyone noticing.
    """
    path = FIXTURES / f"{name}.json"
    assert path.exists(), (
        f"missing fixture {path}. Record it with "
        "`uv run python scripts/smoke_llm.py --yes` (spends well under a cent)."
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    for key in ("recorded_at", *required):
        assert key in payload, f"{path.name} is off-schema: no {key!r} (see README.md)"
    return payload


class Snippet(BaseModel):
    language: str
    word_count: int
    followed_instructions: bool


def a_prompt() -> Prompt:
    return Prompt(
        name="smoke_ping",
        version=1,
        template="Read {snippet}",
        untrusted_vars=frozenset({"snippet"}),
    )


class FakeSession:
    """Captures inserts; answers both budget aggregates with zero."""

    def __init__(self) -> None:
        self.inserts: list[dict[str, Any]] = []

    async def execute(self, statement: Any, parameters: Any = None, /) -> Any:
        if str(statement).lstrip().startswith("INSERT"):
            self.inserts.append(dict(parameters or {}))
        return SimpleNamespace(scalar_one=lambda: Decimal("0"))


class FakeCompletions:
    def __init__(self, replies: list[Any]) -> None:
        self.replies = list(replies)
        self.requests: list[dict[str, Any]] = []

    async def create(self, **body: Any) -> Any:
        self.requests.append(body)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


def recorded_completion(exchange: dict[str, Any]) -> SimpleNamespace:
    """Rebuild the SDK object from what the API actually returned."""
    usage = exchange["response"]["usage"]
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=json.dumps(exchange["response"]["value"])),
                finish_reason="stop",
            )
        ],
        usage=SimpleNamespace(
            prompt_tokens=usage["input_tokens"],
            completion_tokens=usage["output_tokens"],
            total_tokens=usage["total_tokens"],
        ),
    )


@pytest.fixture
def wired(monkeypatch: pytest.MonkeyPatch):
    settings = Settings(
        _env_file=None,
        nebius_api_key="synthetic",
        nebius_base_url="https://api.tokenfactory.nebius.com/v1/",
        model_fast=FAST,
        model_mid=MID,
        model_deep=DEEP,
        model_embed=EMBED,
        daily_budget_usd=Decimal("10"),
        total_budget_usd=Decimal("29"),
        run_budget_usd=Decimal("5"),
        max_call_cost_usd=Decimal("1"),
        llm_max_retries=2,
    )
    monkeypatch.setattr(llm_module, "get_settings", lambda: settings)
    monkeypatch.setattr(llm_module.budget_module, "get_settings", lambda: settings)

    async def no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr(llm_module.asyncio, "sleep", no_sleep)

    def install(replies: list[Any], vector: list[float] | None = None):
        completions = FakeCompletions(replies)
        client = SimpleNamespace(
            chat=SimpleNamespace(completions=completions),
            embeddings=SimpleNamespace(
                create=lambda **_: _embedding_reply(vector or [0.0] * EMBED_DIM_EXPECTED)
            ),
            models=SimpleNamespace(list=lambda: _models_reply()),
        )
        monkeypatch.setattr(llm_module, "get_client", lambda: client)
        return completions

    return install


async def _embedding_reply(vector: list[float]) -> Any:
    return SimpleNamespace(
        data=[SimpleNamespace(embedding=vector)],
        usage=SimpleNamespace(prompt_tokens=4, total_tokens=4),
    )


async def _models_reply() -> Any:
    payload = load("list_models", "models")
    return SimpleNamespace(data=[SimpleNamespace(id=i) for i in payload["models"]])


# --- tier routing ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("tier", "expected"),
    [(ModelTier.FAST, FAST), (ModelTier.MID, MID), (ModelTier.DEEP, DEEP)],
)
def test_each_tier_resolves_to_its_configured_id(wired, tier: ModelTier, expected: str) -> None:
    wired([])
    assert llm_module.resolve_model(tier) == expected


def test_an_unset_tier_raises_config_error_naming_the_variable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(llm_module, "get_settings", lambda: Settings(_env_file=None))
    with pytest.raises(ConfigError, match="MODEL_MID"):
        llm_module.resolve_model(ModelTier.MID)


# --- validation and costing -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_every_recorded_reply_validates_and_costs_exactly(wired) -> None:
    payload = load("complete_json", "exchanges")
    assert payload["exchanges"], "complete_json.json recorded no exchanges"

    for exchange in payload["exchanges"]:
        completions = wired([recorded_completion(exchange)])
        session = FakeSession()
        result = await llm_module.complete_json(
            tier=ModelTier.FAST,
            prompt=a_prompt(),
            variables={"snippet": Untrusted("replayed")},
            output_model=Snippet,
            purpose="replay",
            run=RunContext(),
            session=session,
            max_tokens=exchange["request"]["max_tokens"],
        )
        expected_value = exchange["response"]["value"]
        assert result.value == Snippet.model_validate(expected_value)
        assert result.model == exchange["response"]["model"]

        usage = exchange["response"]["usage"]
        assert result.usage.input_tokens == usage["input_tokens"]
        assert result.cost_usd == pricing.estimate_cost(
            exchange["response"]["model"], usage["input_tokens"], usage["output_tokens"]
        )
        assert isinstance(result.cost_usd, Decimal)
        assert completions.requests[0]["reasoning_effort"] == "none"


def test_the_recorded_request_nests_the_schema_under_json_schema_schema() -> None:
    """What was actually sent and accepted, not what the docs said (D13)."""
    exchange = load("complete_json", "exchanges")["exchanges"][0]
    fmt = exchange["request"]["response_format"]
    assert fmt["type"] == "json_schema"
    assert "schema" in fmt["json_schema"]
    assert "properties" in fmt["json_schema"]["schema"]


def test_the_recorded_request_carried_reasoning_effort_none() -> None:
    """D12: without it the schema did not constrain the output at all."""
    for exchange in load("complete_json", "exchanges")["exchanges"]:
        assert exchange["request"]["reasoning_effort"] == "none"


def test_the_model_did_not_follow_instructions_inside_the_fence() -> None:
    """The live run's evidence that fencing holds against a real model (CLAUDE.md #7)."""
    for exchange in load("complete_json", "exchanges")["exchanges"]:
        assert exchange["response"]["value"]["followed_instructions"] is False


# --- the ledger -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_one_row_is_written_per_attempt_with_the_audit_fields(wired) -> None:
    exchange = load("complete_json", "exchanges")["exchanges"][0]
    wired([recorded_completion(exchange)])
    session = FakeSession()
    run = RunContext()
    prompt = a_prompt()

    await llm_module.complete_json(
        tier=ModelTier.FAST,
        prompt=prompt,
        variables={"snippet": Untrusted("replayed")},
        output_model=Snippet,
        purpose="replay",
        run=run,
        session=session,
    )

    (row,) = session.inserts
    assert row["run_id"] == run.run_id
    assert row["prompt_version"] == prompt.version_label == "smoke_ping.v1"
    assert row["ok"] is True
    assert row["latency_ms"] is not None and row["latency_ms"] >= 0
    assert row["provider"] == "nebius"
    assert row["input_tokens"] == exchange["response"]["usage"]["input_tokens"]


@pytest.mark.asyncio
async def test_a_failed_attempt_is_also_recorded_with_zero_cost(wired) -> None:
    """The retry path: a 5xx then the recorded success. Both attempts get a row (D4)."""
    exchange = load("complete_json", "exchanges")["exchanges"][0]
    response = SimpleNamespace(status_code=503, headers={"retry-after": "0"}, request=None)
    failure = openai.APIStatusError("upstream", response=response, body=None)  # type: ignore[arg-type]

    wired([failure, recorded_completion(exchange)])
    session = FakeSession()
    result = await llm_module.complete_json(
        tier=ModelTier.FAST,
        prompt=a_prompt(),
        variables={"snippet": Untrusted("replayed")},
        output_model=Snippet,
        purpose="replay",
        run=RunContext(),
        session=session,
    )

    assert result.value.language == exchange["response"]["value"]["language"]
    assert len(session.inserts) == 2
    failed, succeeded = session.inserts
    assert failed["ok"] is False
    assert failed["cost_usd"] == Decimal("0")
    assert failed["input_tokens"] is None
    assert failed["error"]
    assert succeeded["ok"] is True
    assert succeeded["cost_usd"] > Decimal("0")


# --- the embedding --------------------------------------------------------------------------


def test_the_recorded_vector_length_is_the_expected_dimension() -> None:
    payload = load("embed", "model", "dimensions", "vector_length")
    assert payload["vector_length"] == EMBED_DIM_EXPECTED
    assert payload["dimensions"] == EMBED_DIM_EXPECTED
    assert payload["model"] == EMBED


@pytest.mark.asyncio
async def test_embed_replays_and_sends_the_dimensions_parameter(wired) -> None:
    payload = load("embed", "vector_length")
    wired([], vector=[0.1] * payload["vector_length"])
    result = await llm_module.embed(
        text="three word input", purpose="replay", run=RunContext(), session=FakeSession()
    )
    assert len(result.value) == EMBED_DIM_EXPECTED


# --- list_models ----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_models_replays_the_recorded_catalog(wired) -> None:
    wired([])
    models = await llm_module.list_models()
    recorded = load("list_models", "models")["models"]
    assert models == recorded
    assert FAST in models and EMBED in models


def test_every_configured_tier_id_was_present_in_the_recorded_catalog() -> None:
    """Catches a MODEL_* id drifting away from what Token Factory actually serves."""
    recorded = set(load("list_models", "models")["models"])
    for model in (FAST, MID, DEEP, EMBED):
        assert model in recorded, f"{model} was not in the recorded catalog"


def test_every_configured_tier_id_has_a_price() -> None:
    prices = pricing.load_prices()
    for model in (FAST, MID, DEEP, EMBED):
        assert model in prices, f"{model} has no pricing.json entry; price_for would raise"
