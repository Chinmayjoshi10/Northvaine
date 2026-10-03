"""brain/llm.py: the single, auditable door to every model call (CLAUDE.md #8).

Every signature here is frozen for milestone 2 (factory/board/M2/PLAN.md, "Frozen contracts").
T2.4 fills in the bodies; nothing here makes a network call. Importing this module builds no
`Settings`, opens no connection and needs no API key — any `Settings` instance and the `openai`
client are constructed inside each function, never at import time.

This is the only file allowed to `import openai` (`scripts/check_invariants.py` enforces it,
CLAUDE.md #8): model routing, Pydantic-validated output, retries, the four-level budget guard
(brain/budget.py) and the `llm_calls` ledger all have exactly one place to look.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TypeVar
from uuid import UUID

from openai import AsyncOpenAI  # noqa: F401 -- frozen contract import; T2.4 constructs the client
from pydantic import BaseModel

from northvaine.brain import pricing
from northvaine.brain.budget import RunContext
from northvaine.brain.prompts import Prompt
from northvaine.core.models import LlmResult, LlmUsage, ModelTier

T = TypeVar("T", bound=BaseModel)


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
) -> LlmResult[T]:
    """Render `prompt`, call `tier`'s model with a schema-constrained `response_format`
    (`json_schema.schema`, `strict: true` — confirmed P2), and validate the reply into
    `output_model` with one repair retry on invalid JSON.

    Checks the budget guard before the call and writes an `llm_calls` row for every attempt,
    success or failure (DECISIONS D2, D4). `reasoning_effort` defaults to `"none"` (DECISIONS
    D12): without it Nemotron spends its whole token budget thinking into `message.content` and
    the JSON schema does not constrain the output at all.
    """
    raise NotImplementedError


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
) -> LlmResult[str]:
    """Like `complete_json`, but the raw text reply with no schema or validation."""
    raise NotImplementedError


async def embed(
    *, text: str, purpose: str, run: RunContext, workspace_id: UUID | None = None
) -> LlmResult[list[float]]:
    """Embed `text` on `settings.model_embed` with `dimensions=core.standards.EMBED_DIM_EXPECTED`.

    Asserts the returned vector has exactly `EMBED_DIM_EXPECTED` floats (DECISIONS D7, D14).
    """
    raise NotImplementedError


async def list_models() -> list[str]:
    """The free `GET /v1/models` listing: every model id Token Factory currently serves."""
    raise NotImplementedError


def estimate_cost(model: str, usage: LlmUsage) -> Decimal:
    """Exact `Decimal` cost of `usage` on `model` (delegates to `brain.pricing.estimate_cost`)."""
    return pricing.estimate_cost(model, usage.input_tokens, usage.output_tokens)
