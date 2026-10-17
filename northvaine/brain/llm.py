"""brain/llm.py: the single, auditable door to every model call (CLAUDE.md #8).

This is the only file allowed to `import openai` (`scripts/check_invariants.py` enforces it):
model routing, Pydantic-validated output, retries, the four-level budget guard (brain/budget.py)
and the `llm_calls` ledger all have exactly one place to look.

Nothing here runs at import time: no `Settings` is built, no client constructed and no key read.
The client is created lazily on first use and cached per (base_url, key, timeout).

Three facts here were measured against the live API on 3 Oct 2026, not read off documentation
(probe P1-P3, `docs/integrations/nebius-token-factory-api-surface-and-client.md`):

1. The schema nests under `response_format.json_schema.schema`. A flat shape is rejected 422.
2. **`reasoning_effort="none"` is required.** Without it Nemotron spends its whole token budget
   thinking in prose into `message.content`, returns `finish_reason: "length"`, and the JSON
   schema does not constrain the output at all. With it: `finish_reason: "stop"` and exact
   schema-valid JSON in 14 tokens. This is the single largest avoidable cost and failure mode.
3. The API returns no `max_output_tokens`; only `context_length`. The output bound is ours.
"""

from __future__ import annotations

import asyncio
import json
import random
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from decimal import Decimal
from functools import lru_cache
from typing import Any, TypeVar
from uuid import UUID

import openai
from openai import AsyncOpenAI
from pydantic import BaseModel, ValidationError

from northvaine.brain import budget as budget_module
from northvaine.brain import pricing
from northvaine.brain.budget import RunContext
from northvaine.brain.errors import (
    LlmInvalidOutput,
    LlmTimeout,
    LlmTransportError,
)
from northvaine.brain.prompts import Prompt
from northvaine.core.models import LlmResult, LlmUsage, ModelTier
from northvaine.core.settings import ConfigError, get_settings
from northvaine.core.standards import EMBED_DIM_EXPECTED

T = TypeVar("T", bound=BaseModel)

DEFAULT_MAX_TOKENS = 1024
BACKOFF_BASE_SECONDS = 1.0
BACKOFF_MAX_SECONDS = 20.0
PROVIDER = "nebius"

TIER_SETTING = {
    ModelTier.FAST: ("model_fast", "MODEL_FAST"),
    ModelTier.MID: ("model_mid", "MODEL_MID"),
    ModelTier.DEEP: ("model_deep", "MODEL_DEEP"),
    ModelTier.EMBED: ("model_embed", "MODEL_EMBED"),
}


def resolve_model(tier: ModelTier) -> str:
    """The configured model id for `tier`, or `ConfigError` naming the variable."""
    attribute, variable = TIER_SETTING[ModelTier(tier)]
    model = getattr(get_settings(), attribute)
    if not model:
        raise ConfigError(f"{variable} is not set; it is required for the {tier} tier.")
    return str(model)


@lru_cache(maxsize=4)
def _cached_client(base_url: str, key: str, timeout: float) -> AsyncOpenAI:
    return AsyncOpenAI(base_url=base_url, api_key=key, timeout=timeout, max_retries=0)


# Set by `client_override`; `get_client` returns it before any settings check (T4.0).
_CLIENT_OVERRIDE: ContextVar[Any] = ContextVar("northvaine_llm_client_override", default=None)


@contextmanager
def client_override(client: Any) -> Iterator[None]:
    """Make `get_client()` return `client` inside the block (recorder, replay, tests).

    Only the client is swapped, so every call still goes through the budget guard and writes
    its `llm_calls` row. Isolated per task (ContextVar) and restored on exit, also on error.
    """
    token = _CLIENT_OVERRIDE.set(client)
    try:
        yield
    finally:
        _CLIENT_OVERRIDE.reset(token)


def get_client() -> AsyncOpenAI:
    """The lazily built, cached SDK client (or the `client_override` one).

    The key is held as `SecretStr` in settings and only unwrapped here, at the moment it is
    handed to the SDK. It is never logged, never formatted into an exception and never written
    to an `llm_calls` row.
    """
    override = _CLIENT_OVERRIDE.get()
    if override is not None:
        return override  # type: ignore[no-any-return]
    settings = get_settings()
    if settings.nebius_api_key is None:
        raise ConfigError("NEBIUS_API_KEY is not set; no model call can be made.")
    if not settings.nebius_base_url:
        raise ConfigError("NEBIUS_BASE_URL is not set; no model call can be made.")
    return _cached_client(
        settings.nebius_base_url,
        settings.nebius_api_key.get_secret_value(),
        settings.llm_timeout_seconds,
    )


def build_request(
    *,
    model: str,
    rendered: str,
    max_tokens: int,
    reasoning_effort: str,
    output_model: type[BaseModel] | None = None,
) -> dict[str, Any]:
    """The exact request body, in the shape probe P2 confirmed.

    Kept separate from the call so tests can assert the body without a network round trip.
    """
    body: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user", "content": rendered}],
        "max_tokens": max_tokens,
        "temperature": 0,
        "reasoning_effort": reasoning_effort,
    }
    if output_model is not None:
        body["response_format"] = {
            "type": "json_schema",
            "json_schema": {
                "name": output_model.__name__,
                "strict": True,
                # Nested under `schema`: a flat shape is rejected 422 (probe P2, D13).
                "schema": output_model.model_json_schema(),
            },
        }
    return body


def estimate_input_tokens(text: str) -> int:
    """A deliberate over-estimate: ~4 characters per token, rounded up.

    M2 has no local tokenizer (parked in docs/LATER.md). Over-estimating fails safe: the guard
    stops a call that might have fitted, rather than letting one through that does not.
    """
    return max(1, -(-len(text) // 3))


def _usage_from(raw: Any) -> LlmUsage:
    usage = getattr(raw, "usage", None)
    if usage is None:
        return LlmUsage(input_tokens=0, output_tokens=0, total_tokens=0)
    return LlmUsage(
        input_tokens=getattr(usage, "prompt_tokens", 0) or 0,
        output_tokens=getattr(usage, "completion_tokens", 0) or 0,
        total_tokens=getattr(usage, "total_tokens", 0) or 0,
    )


def _retry_after(error: Exception) -> float | None:
    """Token Factory sends `Retry-After` on 429. Honour it rather than guessing."""
    response = getattr(error, "response", None)
    headers = getattr(response, "headers", None) or {}
    try:
        value = headers.get("retry-after") or headers.get("Retry-After")
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _backoff(attempt: int, error: Exception | None = None) -> float:
    if error is not None and (after := _retry_after(error)) is not None:
        return min(after, BACKOFF_MAX_SECONDS)
    return min(BACKOFF_BASE_SECONDS * (2**attempt), BACKOFF_MAX_SECONDS) * (
        0.5 + random.random() / 2
    )


def _is_retryable(error: Exception) -> bool:
    """429 and 5xx retry. Any other 4xx is a request we must fix, not repeat."""
    if isinstance(error, openai.RateLimitError | openai.APIConnectionError):
        return True
    status = getattr(error, "status_code", None)
    return isinstance(status, int) and status >= 500


async def _guarded_call(
    *,
    run: RunContext,
    session: Any,
    model: str,
    purpose: str,
    estimated_cost: Decimal,
    prompt_version: str | None,
    workspace_id: UUID | None,
    case_id: UUID | None,
    operation: Any,
) -> tuple[Any, LlmUsage, Decimal]:
    """One attempt: check the budget, call, record the row whatever happens.

    Every attempt is guarded and recorded, so a retry is both paid for and visible (D4). A second
    attempt is refused if the first one's recorded cost pushed the run over its cap.
    """
    async with run.lock:
        await budget_module.check_budget(run, estimated_cost, session=session)

    loop = asyncio.get_running_loop()
    started = loop.time()
    try:
        raw = await operation()
    except Exception as error:  # recorded, classified, then re-raised
        latency_ms = int((loop.time() - started) * 1000)
        async with run.lock:
            await budget_module.record_call(
                run,
                session=session,
                model=model,
                purpose=purpose,
                usage=None,
                cost_usd=Decimal("0"),
                ok=False,
                error=type(error).__name__ + ": " + str(error),
                latency_ms=latency_ms,
                workspace_id=workspace_id,
                case_id=case_id,
                prompt_version=prompt_version,
                provider=PROVIDER,
            )
        raise

    latency_ms = int((loop.time() - started) * 1000)
    usage = _usage_from(raw)
    cost = pricing.estimate_cost(model, usage.input_tokens, usage.output_tokens)
    async with run.lock:
        await budget_module.record_call(
            run,
            session=session,
            model=model,
            purpose=purpose,
            usage=usage,
            cost_usd=cost,
            ok=True,
            error=None,
            latency_ms=latency_ms,
            workspace_id=workspace_id,
            case_id=case_id,
            prompt_version=prompt_version,
            provider=PROVIDER,
        )
    return raw, usage, cost


def _classify(error: Exception) -> Exception:
    if isinstance(error, openai.APITimeoutError):
        return LlmTimeout(f"the model call timed out: {type(error).__name__}")
    if isinstance(error, openai.APIError | openai.OpenAIError):
        status = getattr(error, "status_code", None)
        return LlmTransportError(f"the model call failed (status={status})")
    return error


async def _complete(
    *,
    tier: ModelTier,
    prompt: Prompt,
    variables: dict[str, object],
    output_model: type[T] | None,
    purpose: str,
    run: RunContext,
    session: Any,
    workspace_id: UUID | None,
    case_id: UUID | None,
    reasoning_effort: str,
    max_tokens: int,
) -> tuple[Any, LlmUsage, Decimal, str]:
    model = resolve_model(tier)
    rendered = prompt.render(**variables)  # type: ignore[arg-type]
    estimated = pricing.estimate_cost(model, estimate_input_tokens(rendered), max_tokens)
    settings = get_settings()
    client = get_client()

    body = build_request(
        model=model,
        rendered=rendered,
        max_tokens=max_tokens,
        reasoning_effort=reasoning_effort,
        output_model=output_model,
    )

    last: Exception | None = None
    repair_note: str | None = None
    for attempt in range(settings.llm_max_retries + 1):
        request = dict(body)
        if repair_note:
            request["messages"] = [
                *body["messages"],
                {"role": "user", "content": repair_note},
            ]
        try:
            raw, usage, cost = await _guarded_call(
                run=run,
                session=session,
                model=model,
                purpose=purpose,
                estimated_cost=estimated,
                prompt_version=prompt.version_label,
                workspace_id=workspace_id,
                case_id=case_id,
                operation=lambda r=request: client.chat.completions.create(**r),
            )
        except Exception as error:
            classified = _classify(error)
            if not _is_retryable(error) or attempt == settings.llm_max_retries:
                raise classified from error
            last = error
            await asyncio.sleep(_backoff(attempt, error))
            continue

        content = raw.choices[0].message.content or ""
        if output_model is None:
            return content, usage, cost, model
        try:
            return output_model.model_validate_json(content), usage, cost, model
        except (ValidationError, json.JSONDecodeError) as error:
            last = error
            if attempt == settings.llm_max_retries:
                raise LlmInvalidOutput(
                    f"{model} returned output that does not match {output_model.__name__} "
                    f"after {attempt + 1} attempts"
                ) from error
            repair_note = (
                "Your previous reply did not match the required JSON schema. "
                f"The validation error was: {error}. "
                "Reply again with only the JSON object, matching the schema exactly."
            )

    raise LlmInvalidOutput(f"{model} produced no usable reply") from last


async def complete_json(
    *,
    tier: ModelTier,
    prompt: Prompt,
    variables: dict[str, object],
    output_model: type[T],
    purpose: str,
    run: RunContext,
    workspace_id: UUID | None = None,
    case_id: UUID | None = None,
    reasoning_effort: str = "none",
    session: Any = None,
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> LlmResult[T]:
    """Render `prompt`, call `tier`'s model with a schema-constrained `response_format`
    (`json_schema.schema`, `strict: true` - confirmed P2), and validate the reply into
    `output_model`, retrying with the validation error fed back.

    Checks the budget guard before every attempt and writes an `llm_calls` row after each one,
    success or failure (D2, D4). `reasoning_effort` defaults to `"none"` (D12).
    """
    value, usage, cost, model = await _complete(
        tier=tier,
        prompt=prompt,
        variables=variables,
        output_model=output_model,
        purpose=purpose,
        run=run,
        session=session,
        workspace_id=workspace_id,
        case_id=case_id,
        reasoning_effort=reasoning_effort,
        max_tokens=max_tokens,
    )
    return LlmResult[output_model](value=value, usage=usage, cost_usd=cost, model=model)


async def complete_text(
    *,
    tier: ModelTier,
    prompt: Prompt,
    variables: dict[str, object],
    purpose: str,
    run: RunContext,
    workspace_id: UUID | None = None,
    case_id: UUID | None = None,
    reasoning_effort: str = "none",
    session: Any = None,
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> LlmResult[str]:
    """Like `complete_json`, but the raw text reply with no schema or validation."""
    value, usage, cost, model = await _complete(
        tier=tier,
        prompt=prompt,
        variables=variables,
        output_model=None,
        purpose=purpose,
        run=run,
        session=session,
        workspace_id=workspace_id,
        case_id=case_id,
        reasoning_effort=reasoning_effort,
        max_tokens=max_tokens,
    )
    return LlmResult[str](value=value, usage=usage, cost_usd=cost, model=model)


async def embed(
    *,
    text: str,
    purpose: str,
    run: RunContext,
    workspace_id: UUID | None = None,
    session: Any = None,
) -> LlmResult[list[float]]:
    """Embed `text` with `dimensions=EMBED_DIM_EXPECTED`.

    Raises if the returned vector's length differs, so a model or config change can never
    silently write mis-sized vectors into the columns 0003 sized (D7, D14).
    """
    model = resolve_model(ModelTier.EMBED)
    client = get_client()
    estimated = pricing.estimate_cost(model, estimate_input_tokens(text), 0)

    raw, usage, cost = await _guarded_call(
        run=run,
        session=session,
        model=model,
        purpose=purpose,
        estimated_cost=estimated,
        prompt_version=None,
        workspace_id=workspace_id,
        case_id=None,
        operation=lambda: client.embeddings.create(
            model=model, input=text, dimensions=EMBED_DIM_EXPECTED
        ),
    )

    vector = list(raw.data[0].embedding)
    if len(vector) != EMBED_DIM_EXPECTED:
        raise LlmInvalidOutput(
            f"{model} returned a {len(vector)}-dimension vector; "
            f"EMBED_DIM_EXPECTED is {EMBED_DIM_EXPECTED} and the database columns are sized to "
            "it. Re-probe the endpoint before writing any embedding."
        )
    return LlmResult[list[float]](value=vector, usage=usage, cost_usd=cost, model=model)


async def list_models() -> list[str]:
    """The free `GET /v1/models` listing: every model id Token Factory currently serves.

    Not billed, so it skips the budget path - but it still goes through the one place the SDK is
    constructed, so no script needs its own HTTP client.
    """
    client = get_client()
    try:
        page = await client.models.list()
    except Exception as error:
        raise _classify(error) from error
    return [model.id for model in page.data]


def estimate_cost(model: str, usage: LlmUsage) -> Decimal:
    """Exact `Decimal` cost of `usage` on `model` (delegates to `brain.pricing.estimate_cost`)."""
    return pricing.estimate_cost(model, usage.input_tokens, usage.output_tokens)
