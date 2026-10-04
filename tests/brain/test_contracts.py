"""The frozen M2 contracts (factory/board/M2/PLAN.md, "Frozen contracts") exist as specified.

Checks shape only: names, `inspect.signature` parameter names/kinds/defaults, field sets, and
that importing any `brain` module builds no `Settings`, opens no connection and needs no API
key. Never asserts that a stub raises `NotImplementedError` — that would block the very tickets
that implement them (T2.2-T2.5).
"""

from __future__ import annotations

import ast
import inspect
import os
import subprocess
import sys
import textwrap
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import BaseModel, ValidationError

from northvaine.brain import budget, errors, fencing, llm, pricing
from northvaine.brain import prompts as prompts_module
from northvaine.brain.prompts import Prompt, load_prompt
from northvaine.core.models import (
    BudgetKind,
    LlmCallRow,
    LlmResult,
    LlmUsage,
    ModelPrice,
)
from northvaine.core.settings import ConfigError, Settings

P = inspect.Parameter
POS = P.POSITIONAL_OR_KEYWORD
KW = P.KEYWORD_ONLY
NO = P.empty


def params(func: object) -> list[tuple[str, inspect._ParameterKind, object]]:
    sig = inspect.signature(func)  # type: ignore[arg-type]
    return [(p.name, p.kind, p.default) for p in sig.parameters.values()]


# --- importing brain/ needs nothing live --------------------------------------------------


def test_brain_imports_without_env_or_api_key(tmp_path: Path) -> None:
    """Fresh interpreter, no .env, no NEBIUS_API_KEY: every brain module still imports."""
    code = textwrap.dedent(
        """
        import northvaine.brain.llm
        import northvaine.brain.budget
        import northvaine.brain.fencing
        import northvaine.brain.pricing
        import northvaine.brain.errors
        import northvaine.brain.prompts
        """
    )
    hidden = {"NEBIUS_API_KEY", "DATABASE_URL", "TEST_DATABASE_URL"}
    env = {k: v for k, v in os.environ.items() if k.upper() not in hidden}
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[2])
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_importing_brain_builds_no_settings_instance() -> None:
    """No Settings is constructed at import time - reading them inside a function is fine.

    T2.3's check_budget must read the four caps, so it calls get_settings() in its body. The
    property that matters is that importing the module does not, which is what this now checks
    (a banned substring would have forbidden the legitimate call too).
    """
    for module in (llm, budget, fencing, pricing, errors):
        path = Path(module.__file__)  # type: ignore[arg-type]
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:  # module level only; function bodies are not walked
            for call in (
                ast.walk(node)
                if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)
                else []
            ):
                if isinstance(call, ast.Call):
                    name = getattr(call.func, "id", getattr(call.func, "attr", ""))
                    assert name not in {"Settings", "get_settings"}, f"{path.name}: {name}()"


# --- core/models.py: LlmUsage, ModelPrice, LlmResult[T], BudgetKind ------------------------


def test_budget_kind_values() -> None:
    assert [k.value for k in BudgetKind] == ["call", "run", "day", "total"]


def test_llm_usage_rejects_unknown_fields() -> None:
    usage = LlmUsage(input_tokens=10, output_tokens=5, total_tokens=15)
    assert usage.total_tokens == 15
    with pytest.raises(ValidationError):
        LlmUsage(input_tokens=1, output_tokens=1, total_tokens=2, extra=1)  # type: ignore[call-arg]


def test_model_price_fields() -> None:
    price = ModelPrice(
        model="nvidia/Nemotron-3_5-Lightning",
        usd_per_million_input=Decimal("0.06"),
        usd_per_million_output=Decimal("0.24"),
        context_length=1_048_576,
        checked_on=date(2026, 10, 3),
        source_url="https://api.tokenfactory.nebius.com/v1/models?verbose=true",
    )
    assert price.context_length == 1_048_576
    assert isinstance(price.usd_per_million_input, Decimal)


def test_model_price_embed_has_no_output_price() -> None:
    price = ModelPrice(
        model="Qwen/Qwen3-Embedding-8B",
        usd_per_million_input=Decimal("0.01"),
        usd_per_million_output=None,
        context_length=40_960,
        checked_on=date(2026, 10, 3),
        source_url="https://api.tokenfactory.nebius.com/v1/models?verbose=true",
    )
    assert price.usd_per_million_output is None


class _Answer(BaseModel):
    city: str
    country: str


def test_llm_result_parameterizes_and_validates() -> None:
    usage = LlmUsage(input_tokens=10, output_tokens=5, total_tokens=15)
    result = LlmResult[_Answer](
        value=_Answer(city="Paris", country="France"),
        usage=usage,
        cost_usd=Decimal("0.0001"),
        model="nvidia/Nemotron-3_5-Lightning",
    )
    assert isinstance(result.value, _Answer)
    assert result.value.city == "Paris"
    with pytest.raises(ValidationError):
        LlmResult[_Answer](value={"city": "Paris"}, usage=usage, cost_usd=Decimal("0"), model="x")


def test_llm_call_row_has_the_four_new_columns() -> None:
    assert {"run_id", "prompt_version", "latency_ms", "error"} <= set(LlmCallRow.model_fields)


# --- brain/errors.py ------------------------------------------------------------------------


def test_config_error_is_not_redefined() -> None:
    assert errors.ConfigError is ConfigError


def test_error_hierarchy() -> None:
    for cls in (errors.LlmTimeout, errors.LlmTransportError, errors.LlmInvalidOutput):
        assert issubclass(cls, errors.LlmError)
    assert issubclass(errors.PricingUnknown, errors.LlmError)
    assert issubclass(errors.BudgetExceeded, errors.LlmError)


def test_replay_mismatch_is_an_assertion_error() -> None:
    """T4.0: a recorded-replay miss is a test failure, never retried or classified by llm.py."""
    assert issubclass(errors.LlmReplayMismatch, AssertionError)
    assert not issubclass(errors.LlmReplayMismatch, errors.LlmError)


def test_client_override_is_a_sync_context_manager_taking_one_client() -> None:
    assert params(llm.client_override) == [("client", POS, NO)]
    assert not inspect.iscoroutinefunction(llm.client_override)


def test_budget_exceeded_message_names_the_cap() -> None:
    exc = errors.BudgetExceeded(BudgetKind.DAY, Decimal("1.00"), Decimal("0.95"), Decimal("0.10"))
    assert "day" in str(exc)
    assert "1.00" in str(exc)
    assert exc.kind is BudgetKind.DAY


def test_pricing_unknown_names_the_model() -> None:
    exc = errors.PricingUnknown("made/up-model")
    assert "made/up-model" in str(exc)
    assert exc.model == "made/up-model"


# --- brain/pricing.py -----------------------------------------------------------------------


def test_load_prices_validates_against_model_price() -> None:
    prices = pricing.load_prices()
    assert "nvidia/Nemotron-3_5-Lightning" in prices
    assert "Qwen/Qwen3-Embedding-8B" in prices
    for price in prices.values():
        assert isinstance(price, ModelPrice)


def test_price_for_unknown_id_raises_pricing_unknown() -> None:
    with pytest.raises(errors.PricingUnknown):
        pricing.price_for("made/up-model")


def test_estimate_cost_is_exact_decimal_arithmetic() -> None:
    cost = pricing.estimate_cost("nvidia/Nemotron-3_5-Lightning", 1_000_000, 1_000_000)
    assert cost == Decimal("0.06") + Decimal("0.24")
    assert isinstance(cost, Decimal)


def test_estimate_cost_path_has_no_float() -> None:
    source = Path(pricing.__file__).read_text(encoding="utf-8")  # type: ignore[arg-type]
    assert "float(" not in source


def test_validate_configured_models_reports_all_missing_ids_in_one_error() -> None:
    settings = Settings(
        _env_file=None,
        model_fast="made/up-fast",  # type: ignore[call-arg]
        model_mid="made/up-mid",  # type: ignore[call-arg]
        model_deep="nvidia/Nemotron-3-Ultra-550b-a55b",  # type: ignore[call-arg]
        model_embed="Qwen/Qwen3-Embedding-8B",  # type: ignore[call-arg]
    )
    with pytest.raises(ConfigError) as exc_info:
        pricing.validate_configured_models(settings)
    message = str(exc_info.value)
    assert "MODEL_FAST" in message
    assert "MODEL_MID" in message


def test_validate_configured_models_passes_with_real_ids() -> None:
    settings = Settings(
        _env_file=None,
        model_fast="nvidia/Nemotron-3_5-Lightning",  # type: ignore[call-arg]
        model_mid="nvidia/nemotron-3-super-120b-a12b",  # type: ignore[call-arg]
        model_deep="nvidia/Nemotron-3-Ultra-550b-a55b",  # type: ignore[call-arg]
        model_embed="Qwen/Qwen3-Embedding-8B",  # type: ignore[call-arg]
    )
    pricing.validate_configured_models(settings)  # must not raise


# --- brain/llm.py, budget.py, fencing.py, prompts/: frozen signatures ------------------------

# T2.4 adds two keyword-only parameters to the three call entry points. Both are required by
# findings that postdate the frozen contract, not conveniences:
#   `session`  - check_budget and record_call need it. Without a session the day and lifetime
#                caps are never summed, so the two caps that protect the wallet across processes
#                would silently not apply (D1, D3).
#   `max_tokens` - probe P1 found the API publishes no max_output_tokens, only context_length,
#                so the output bound has to come from the caller (T2.0 "two traps").
LLM_CONTRACT = {
    "complete_json": [
        ("tier", KW, NO),
        ("prompt", KW, NO),
        ("variables", KW, NO),
        ("output_model", KW, NO),
        ("purpose", KW, NO),
        ("run", KW, NO),
        ("workspace_id", KW, None),
        ("case_id", KW, None),
        ("reasoning_effort", KW, "none"),
        ("session", KW, None),
        ("max_tokens", KW, 1024),
    ],
    "complete_text": [
        ("tier", KW, NO),
        ("prompt", KW, NO),
        ("variables", KW, NO),
        ("purpose", KW, NO),
        ("run", KW, NO),
        ("workspace_id", KW, None),
        ("case_id", KW, None),
        ("reasoning_effort", KW, "none"),
        ("session", KW, None),
        ("max_tokens", KW, 1024),
    ],
    "embed": [
        ("text", KW, NO),
        ("purpose", KW, NO),
        ("run", KW, NO),
        ("workspace_id", KW, None),
        ("session", KW, None),
    ],
    "list_models": [],
    "estimate_cost": [("model", POS, NO), ("usage", POS, NO)],
}

BUDGET_CONTRACT = {
    "check_budget": [("run", POS, NO), ("estimated_cost", POS, NO), ("session", KW, None)],
    "record_call": [
        ("run", POS, NO),
        ("session", KW, None),
        ("model", KW, NO),
        ("purpose", KW, NO),
        ("usage", KW, NO),
        ("cost_usd", KW, NO),
        ("ok", KW, NO),
        ("error", KW, NO),
        ("latency_ms", KW, NO),
        ("workspace_id", KW, None),
        ("case_id", KW, None),
        ("prompt_version", KW, None),
        # D15 postdates this frozen contract: every row records which API served the call.
        ("provider", KW, "nebius"),
    ],
}

FENCING_CONTRACT = {
    "fence": [("value", POS, NO), ("label", KW, "untrusted")],
}

PROMPTS_CONTRACT = {
    # T2.2 adds the keyword-only version pin its acceptance criteria require:
    # load_prompt(name) takes the highest version, load_prompt(name, version=N) pins one.
    "load_prompt": [("name", POS, NO), ("version", KW, None)],
}


@pytest.mark.parametrize(("name", "expected"), LLM_CONTRACT.items())
def test_llm_signatures(name: str, expected: list[tuple[str, object, object]]) -> None:
    assert params(getattr(llm, name)) == expected


@pytest.mark.parametrize(("name", "expected"), BUDGET_CONTRACT.items())
def test_budget_signatures(name: str, expected: list[tuple[str, object, object]]) -> None:
    assert params(getattr(budget, name)) == expected


@pytest.mark.parametrize(("name", "expected"), FENCING_CONTRACT.items())
def test_fencing_signatures(name: str, expected: list[tuple[str, object, object]]) -> None:
    assert params(getattr(fencing, name)) == expected


@pytest.mark.parametrize(("name", "expected"), PROMPTS_CONTRACT.items())
def test_prompts_signatures(name: str, expected: list[tuple[str, object, object]]) -> None:
    assert params(getattr(prompts_module, name)) == expected


def test_async_kinds() -> None:
    for name in ("complete_json", "complete_text", "embed", "list_models"):
        assert inspect.iscoroutinefunction(getattr(llm, name)), name
    assert not inspect.iscoroutinefunction(llm.estimate_cost)
    for name in ("check_budget", "record_call"):
        assert inspect.iscoroutinefunction(getattr(budget, name)), name
    assert not inspect.iscoroutinefunction(fencing.fence)
    assert not inspect.iscoroutinefunction(load_prompt)


def test_run_context_fields() -> None:
    run = budget.RunContext()
    assert run.workspace_id is None
    assert run.spent_usd == Decimal("0")
    assert run.run_id is not None
    other = budget.RunContext()
    assert run.run_id != other.run_id


def test_untrusted_wraps_a_value() -> None:
    wrapped = fencing.Untrusted("a buyer's reply")
    assert wrapped.value == "a buyer's reply"


def test_prompt_is_a_frozen_dataclass_with_render_and_version_label() -> None:
    prompt = Prompt(name="demo", version=1, template="hi {name}", untrusted_vars=frozenset())
    assert prompt.name == "demo"
    assert prompt.version == 1
    with pytest.raises(AttributeError):
        prompt.name = "other"  # type: ignore[misc]
    assert hasattr(Prompt, "render")
    assert hasattr(Prompt, "version_label")
