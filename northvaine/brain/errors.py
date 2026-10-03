"""The error taxonomy every `brain/` module raises (T2.0 contract).

`ConfigError` is imported, never redefined: it is `northvaine.core.settings.ConfigError`, the
same object, so a caller can catch one exception type across both a missing `.env` value and a
budget or pricing problem discovered later.
"""

from __future__ import annotations

from decimal import Decimal

from northvaine.core.models import BudgetKind
from northvaine.core.settings import ConfigError

__all__ = [
    "BudgetExceeded",
    "ConfigError",
    "LlmError",
    "LlmInvalidOutput",
    "LlmTimeout",
    "LlmTransportError",
    "PricingUnknown",
]


class LlmError(RuntimeError):
    """Base of every error `brain/llm.py` raises."""


class LlmTimeout(LlmError):
    """The call did not finish within `settings.llm_timeout_seconds`."""


class LlmTransportError(LlmError):
    """The HTTP call to Token Factory failed (connection, 5xx, malformed response)."""


class LlmInvalidOutput(LlmError):
    """The model's output could not be parsed into the caller's Pydantic model after retries."""


class PricingUnknown(LlmError):
    """A model id has no `pricing.json` entry. Never falls back to a zero cost."""

    def __init__(self, model: str) -> None:
        super().__init__(f"no pricing.json entry for model {model!r}")
        self.model = model


class BudgetExceeded(LlmError):
    """A call would exceed one of the four money caps. The message names which one."""

    def __init__(
        self, kind: BudgetKind, cap: Decimal, spent: Decimal, would_spend: Decimal
    ) -> None:
        super().__init__(
            f"{kind.value} budget exceeded: cap={cap} spent={spent} would_spend={would_spend}"
        )
        self.kind = kind
        self.cap = cap
        self.spent = spent
        self.would_spend = would_spend
