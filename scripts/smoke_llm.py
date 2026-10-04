"""The one code path in this repository that spends real money (T2.5a).

It is a script, never a pytest test, and nothing in the gate invokes it. It does two jobs:

1. Proves the whole stack works against the live API - routing, the budget guard, the ledger,
   the embedding dimension and the hard stop.
2. **Records the fixtures** every later milestone replays offline for free. One sub-cent run
   buys them; after that no test needs the network.

It imports no HTTP client and no LLM SDK. Everything, including the free model listing, goes
through `brain/llm.py` (CLAUDE.md #8), so there is exactly one place where a call can be made.

Run it with:  uv run python scripts/tasks.py smoke -- --yes
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from pydantic import BaseModel
from sqlalchemy import text

from northvaine.brain import llm
from northvaine.brain.budget import DAY_SUM, TOTAL_SUM, RunContext, utc_day_bounds
from northvaine.brain.errors import BudgetExceeded
from northvaine.brain.fencing import Untrusted
from northvaine.brain.pricing import load_prices, validate_configured_models
from northvaine.brain.prompts import load_prompt
from northvaine.core.db import normalize_database_url
from northvaine.core.models import ModelTier
from northvaine.core.settings import ConfigError, get_settings
from northvaine.core.standards import EMBED_DIM_EXPECTED


def stamp() -> str:
    """Wall-clock UTC for each step: a run that writes an audit ledger should say when."""
    return datetime.now(UTC).strftime("%H:%M:%S")


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "llm"
REQUIRED_HEAD = "0003"
MAX_ESTIMATE_USD = Decimal("0.01")
SMOKE_MAX_TOKENS = 64

SNIPPETS = [
    "Bonjour tout le monde",
    "Guten Morgen alle zusammen",
]

# --- redaction ----------------------------------------------------------------------------

REDACTED = "[REDACTED]"
SECRET_KEYS = {
    "authorization",
    "api_key",
    "apikey",
    "x-api-key",
    "nebius_api_key",
    "key",
    "token",
    "access_token",
    "account_id",
    "account",
    "organization",
    "user",
}
# Word boundary first: page text such as "maersk-nimmt-neues-..." is not a key (D70).
KEY_PATTERN = re.compile(r"(?<![A-Za-z0-9])(nvapi-|sk-|eyJ)[-_A-Za-z0-9.]{12,}")


def redact(value: Any, secrets: tuple[str, ...] = ()) -> Any:
    """Remove the API key, auth headers and account identifiers before anything is written.

    Three places a key hides, each covered by a test: a header, a URL query or path, and a
    nested body field. Literal known secrets are replaced wherever they appear, and anything
    that merely *looks* like a key is replaced too - a fixture is committed to a public repo,
    so this fails closed.
    """
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            if str(key).lower() in SECRET_KEYS:
                out[key] = REDACTED
            else:
                out[key] = redact(item, secrets)
        return out
    if isinstance(value, list):
        return [redact(item, secrets) for item in value]
    if isinstance(value, str):
        text_value = value
        for secret in secrets:
            if secret:
                text_value = text_value.replace(secret, REDACTED)
        return KEY_PATTERN.sub(REDACTED, text_value)
    return value


def known_secrets() -> tuple[str, ...]:
    settings = get_settings()
    found = []
    if settings.nebius_api_key is not None:
        found.append(settings.nebius_api_key.get_secret_value())
    for url in (settings.database_url, settings.test_database_url):
        if url is not None:
            found.append(url.get_secret_value())
    return tuple(found)


def write_fixture(name: str, payload: dict[str, Any]) -> Path:
    FIXTURES.mkdir(parents=True, exist_ok=True)
    path = FIXTURES / f"{name}.json"
    body = redact(payload, known_secrets())
    path.write_text(json.dumps(body, indent=2, default=str) + "\n", encoding="utf-8")
    return path


# --- preconditions ------------------------------------------------------------------------


class Snippet(BaseModel):
    """The tiny schema the smoke prompt asks for."""

    language: str
    word_count: int
    followed_instructions: bool


async def alembic_head(url: str) -> str:
    from sqlalchemy import pool
    from sqlalchemy.ext.asyncio import create_async_engine

    normalized = normalize_database_url(url)
    engine = create_async_engine(
        normalized.url, connect_args=normalized.connect_args, poolclass=pool.NullPool
    )
    try:
        async with engine.begin() as conn:
            result = await conn.execute(text("SELECT version_num FROM alembic_version"))
            return str(result.scalar_one())
    finally:
        await engine.dispose()


def check_preconditions() -> tuple[Any, str]:
    settings = get_settings()

    validate_configured_models(settings)

    for name, value in (
        ("DAILY_BUDGET_USD", settings.daily_budget_usd),
        ("TOTAL_BUDGET_USD", settings.total_budget_usd),
    ):
        if value is None:
            raise ConfigError(f"{name} is not set. Set it in .env before running the smoke test.")

    if settings.database_url is None:
        raise ConfigError("DATABASE_URL is not set; the ledger has nowhere to write.")
    url = settings.database_url.get_secret_value()

    head = asyncio.run(alembic_head(url))
    if head != REQUIRED_HEAD:
        raise ConfigError(
            f"the connected database reports alembic head {head!r}, but the smoke run needs "
            f"{REQUIRED_HEAD!r}: record_call writes run_id, prompt_version, latency_ms, error "
            "and provider. Run `uv run python scripts/tasks.py migrate` first."
        )
    return settings, url


# --- reporting ----------------------------------------------------------------------------


def redact_url(url: str) -> str:
    return re.sub(r"//[^@/]+@", "//[REDACTED]@", url)


async def spend_so_far(session: Any, workspace_id: None = None) -> tuple[Decimal, Decimal]:
    start, end = utc_day_bounds()
    day = await session.execute(
        text(DAY_SUM), {"start": start, "end": end, "workspace_id": workspace_id}
    )
    total = await session.execute(text(TOTAL_SUM))
    return Decimal(str(day.scalar_one())), Decimal(str(total.scalar_one()))


def plan_estimate(settings: Any) -> Decimal:
    prices = load_prices()
    fast = prices[settings.model_fast]
    embed_price = prices[settings.model_embed]
    per_completion = (
        Decimal(400) * fast.usd_per_million_input
        + Decimal(SMOKE_MAX_TOKENS) * (fast.usd_per_million_output or Decimal(0))
    ) / Decimal(1_000_000)
    embed_cost = Decimal(8) * embed_price.usd_per_million_input / Decimal(1_000_000)
    return per_completion * len(SNIPPETS) + embed_cost


def print_plan(settings: Any, url: str, estimate: Decimal, day: Decimal, total: Decimal) -> None:
    prices = load_prices()
    print("=" * 72)
    print("NORTHVAINE LIVE SMOKE RUN - this spends real money")
    print(f"started         : {datetime.now(UTC).isoformat(timespec='seconds')}")
    print("=" * 72)
    print(f"base URL        : {settings.nebius_base_url}")
    print("api key         : [set, never printed]")
    print(f"database        : {redact_url(url)}")
    print(f"alembic head    : {REQUIRED_HEAD}")
    print()
    print("models:")
    for tier, model in (
        ("fast", settings.model_fast),
        ("embed", settings.model_embed),
    ):
        price = prices[model]
        out = price.usd_per_million_output
        print(
            f"  {tier:6} {model:38} ${price.usd_per_million_input}/1M in"
            + (f", ${out}/1M out" if out is not None else "")
            + f"   (checked {price.checked_on})"
        )
    print()
    print("planned calls:")
    print("  1. list_models()                       free")
    print(f"  2. complete_json() x{len(SNIPPETS)}  max_tokens={SMOKE_MAX_TOKENS} each")
    print("  3. embed() on a three-word input")
    print("  4. a deliberately tiny cap, to show the hard stop   free (refused before sending)")
    print()
    print(f"estimated cost  : ${estimate:.6f}  (abort threshold ${MAX_ESTIMATE_USD})")
    print(f"spent today     : ${day:.6f}  of ${settings.daily_budget_usd}")
    print(f"spent lifetime  : ${total:.6f}  of ${settings.total_budget_usd}")
    print(f"headroom        : ${settings.total_budget_usd - total:.6f}")
    print("=" * 72)


# --- the run ------------------------------------------------------------------------------


async def run_smoke(settings: Any, url: str, session: Any) -> int:
    run = RunContext()
    prompt = load_prompt("smoke_ping")
    recorded: list[dict[str, Any]] = []

    print("\n[1/4] list_models() (free)")
    models = await llm.list_models()
    print(f"      {len(models)} models; fast tier present: {settings.model_fast in models}")
    write_fixture("list_models", {"recorded_at": datetime.now(UTC), "models": models})

    print(f"\n[2/4] complete_json() x{len(SNIPPETS)} on {settings.model_fast}")
    for index, snippet in enumerate(SNIPPETS, start=1):
        result = await llm.complete_json(
            tier=ModelTier.FAST,
            prompt=prompt,
            variables={"snippet": Untrusted(snippet)},
            output_model=Snippet,
            purpose="smoke",
            run=run,
            session=session,
            max_tokens=SMOKE_MAX_TOKENS,
        )
        print(
            f"      [{stamp()}] {index}. {result.value.language!r} "
            f"words={result.value.word_count} "
            f"followed_instructions={result.value.followed_instructions} "
            f"[{result.usage.input_tokens}in/{result.usage.output_tokens}out "
            f"${result.cost_usd:.6f}]"
        )
        recorded.append(
            {
                "request": llm.build_request(
                    model=result.model,
                    rendered=prompt.render(snippet=Untrusted(snippet)),
                    max_tokens=SMOKE_MAX_TOKENS,
                    reasoning_effort="none",
                    output_model=Snippet,
                ),
                "response": {
                    "value": result.value.model_dump(),
                    "usage": result.usage.model_dump(),
                    "model": result.model,
                },
            }
        )
    write_fixture(
        "complete_json", {"recorded_at": datetime.now(UTC), "exchanges": recorded}
    )

    print(f"\n[3/4] embed() on {settings.model_embed}")
    embedding = await llm.embed(
        text="three word input", purpose="smoke", run=run, session=session
    )
    dimension = len(embedding.value)
    print(f"      returned {dimension} floats (EMBED_DIM_EXPECTED = {EMBED_DIM_EXPECTED})")
    if dimension != EMBED_DIM_EXPECTED:
        print(f"      FAIL: live dimension {dimension} != {EMBED_DIM_EXPECTED}")
        return 1

    db_dimension = (
        await session.execute(
            text(
                "SELECT atttypmod FROM pg_attribute a "
                "JOIN pg_class c ON c.oid = a.attrelid "
                "WHERE c.relname = 'theses' AND a.attname = 'embedding'"
            )
        )
    ).scalar_one()
    print(f"      database column is vector({db_dimension})")
    if int(db_dimension) != EMBED_DIM_EXPECTED:
        print(f"      FAIL: migration 0003 wrote vector({db_dimension})")
        return 1
    write_fixture(
        "embed",
        {
            "recorded_at": datetime.now(UTC),
            "model": embedding.model,
            "dimensions": EMBED_DIM_EXPECTED,
            "usage": embedding.usage.model_dump(),
            "vector_length": dimension,
            "vector_head": embedding.value[:8],
        },
    )

    print("\n[4/4] the hard stop, for free")
    tiny = RunContext()
    tiny.spent_usd = Decimal("999")
    try:
        await llm.complete_json(
            tier=ModelTier.FAST,
            prompt=prompt,
            variables={"snippet": Untrusted("never sent")},
            output_model=Snippet,
            purpose="smoke-refused",
            run=tiny,
            session=session,
            max_tokens=SMOKE_MAX_TOKENS,
        )
    except BudgetExceeded as stop:
        print(f"      refused before sending: {stop}")
    else:
        print("      FAIL: the guard did not stop an over-cap call")
        return 1

    return 0


async def report(settings: Any, session: Any, run_started: datetime) -> None:
    rows = (
        await session.execute(
            text(
                "SELECT created_at, model, purpose, input_tokens, output_tokens, cost_usd, "
                "ok, latency_ms, provider FROM llm_calls WHERE created_at >= :since ORDER BY id"
            ),
            {"since": run_started},
        )
    ).mappings().all()

    print("\n" + "=" * 72)
    print("llm_calls rows written by this run (read back from the database):")
    for row in rows:
        print(
            f"  {row['created_at'].strftime('%H:%M:%S')} {row['model']:38} "
            f"{row['purpose']:14} "
            f"{row['input_tokens'] or 0:>5}in/{row['output_tokens'] or 0:>4}out "
            f"${Decimal(str(row['cost_usd'])):.6f} ok={row['ok']} "
            f"{row['latency_ms']}ms {row['provider']}"
        )
    day, total = await spend_so_far(session)
    print()
    print(f"finished        : {datetime.now(UTC).isoformat(timespec='seconds')}")
    print(f"spent today     : ${day:.6f}  of ${settings.daily_budget_usd}")
    print(f"spent lifetime  : ${total:.6f}  of ${settings.total_budget_usd}")
    print(f"headroom        : ${settings.total_budget_usd - total:.6f}")
    print(f"fixtures written: {FIXTURES}")
    print("=" * 72)


async def main_async(url: str, settings: Any) -> int:
    from sqlalchemy import pool
    from sqlalchemy.ext.asyncio import create_async_engine

    normalized = normalize_database_url(url)
    engine = create_async_engine(
        normalized.url, connect_args=normalized.connect_args, poolclass=pool.NullPool
    )
    started = datetime.now(UTC)
    try:
        async with engine.begin() as session:
            code = await run_smoke(settings, url, session)
            await report(settings, session, started)
            return code
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--yes", action="store_true", help="actually spend money (required to proceed)"
    )
    args = parser.parse_args(argv)

    settings, url = check_preconditions()

    from sqlalchemy import pool
    from sqlalchemy.ext.asyncio import create_async_engine

    async def current() -> tuple[Decimal, Decimal]:
        normalized = normalize_database_url(url)
        engine = create_async_engine(
            normalized.url, connect_args=normalized.connect_args, poolclass=pool.NullPool
        )
        try:
            async with engine.begin() as session:
                return await spend_so_far(session)
        finally:
            await engine.dispose()

    day, total = asyncio.run(current())
    estimate = plan_estimate(settings)
    print_plan(settings, url, estimate, day, total)

    if estimate > MAX_ESTIMATE_USD:
        print(f"\nABORT: estimate ${estimate} exceeds ${MAX_ESTIMATE_USD}.")
        return 2
    if not args.yes:
        print("\nNothing spent. Re-run with --yes to proceed.")
        return 0

    return asyncio.run(main_async(url, settings))


if __name__ == "__main__":
    sys.exit(main())
