"""Load and look up `pricing.json`: exact `Decimal` arithmetic, never a float, never a guess.

The catalog returns prices per *token* (docs/integrations/nebius-token-factory-api-surface-and-
client.md, probe P1 confirmed note 1); `pricing.json` stores the per-million figure and nothing
here re-scales it again.
"""

from __future__ import annotations

import json
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

from northvaine.brain.errors import PricingUnknown
from northvaine.core.models import ModelPrice
from northvaine.core.settings import ConfigError, Settings

PRICING_PATH = Path(__file__).resolve().parent / "pricing.json"

_MILLION = Decimal(1_000_000)


@lru_cache(maxsize=1)
def load_prices() -> dict[str, ModelPrice]:
    """Parse and Pydantic-validate `pricing.json`, keyed by exact model id."""
    raw = json.loads(PRICING_PATH.read_text(encoding="utf-8"))
    return {model_id: ModelPrice.model_validate(entry) for model_id, entry in raw.items()}


def price_for(model: str) -> ModelPrice:
    """Return the `ModelPrice` for `model`, or raise `PricingUnknown` — never a zero fallback."""
    prices = load_prices()
    try:
        return prices[model]
    except KeyError:
        raise PricingUnknown(model) from None


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> Decimal:
    """Exact `Decimal` cost of a call, from `pricing.json`'s per-million figures."""
    price = price_for(model)
    cost = (Decimal(input_tokens) * price.usd_per_million_input) / _MILLION
    if output_tokens:
        if price.usd_per_million_output is None:
            raise PricingUnknown(model)
        cost += (Decimal(output_tokens) * price.usd_per_million_output) / _MILLION
    return cost


def validate_configured_models(settings: Settings) -> None:
    """Raise one `ConfigError` naming every configured `MODEL_*` id with no pricing entry.

    Checked once, before the first live call: a typo'd id would otherwise fail only at the
    first request — including the smoke run that is supposed to buy the fixtures.
    """
    prices = load_prices()
    configured = {
        "MODEL_FAST": settings.model_fast,
        "MODEL_MID": settings.model_mid,
        "MODEL_DEEP": settings.model_deep,
        "MODEL_EMBED": settings.model_embed,
    }
    missing = [name for name, model_id in configured.items() if model_id and model_id not in prices]
    if missing:
        raise ConfigError(f"no pricing.json entry for {', '.join(sorted(missing))}")
