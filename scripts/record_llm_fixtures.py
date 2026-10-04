"""Record the LLM calls of the evidence ledger as redacted replay fixtures (T4.1, D53).

Orchestrator-only: it needs `.env`, the network and a migrated database, and it spends money
(well under $0.05 for the sample clients). It never runs in the gate and never from pytest.

What it does, in order:

1. Replays the recorded sensor fixtures through `get_sensor` for every client spec, and turns
   `tests/fixtures/web/*.html` into `website` documents. Nothing here touches the network.
2. Without `--yes`: prints the plan (documents per client, estimated calls and cost) and stops.
3. With `--yes`: refuses unless the database is at head 0005 and both budget caps are set, then
   calls `radar.ledger.build_evidence` for every document under
   `llm.client_override(RecordingClient(real_client))`. Only `llm_calls` rows are written to the
   database; no claim or event is ever stored by this script.
4. Redacts every recording with `smoke_llm.redact`, refuses to write if a secret, email or phone
   number survives, and writes `tests/fixtures/llm/ledger/<client>.json` (and `web.json`).

Run it with:  uv run python scripts/tasks.py record-llm -- --yes
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import sys
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from types import ModuleType
from typing import Any

import httpx
from pydantic import SecretStr

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:  # run as a plain script: make `northvaine` importable
    sys.path.insert(0, str(ROOT))

from northvaine.brain import llm  # noqa: E402
from northvaine.brain.budget import RunContext  # noqa: E402
from northvaine.brain.errors import ConfigError  # noqa: E402
from northvaine.brain.pricing import estimate_cost, validate_configured_models  # noqa: E402
from northvaine.brain.replay import (  # noqa: E402
    LlmExchange,
    LlmRecording,
    RecordingClient,
    save_recording,
)
from northvaine.core.models import EvidenceDocument  # noqa: E402
from northvaine.core.settings import Settings, get_settings  # noqa: E402
from northvaine.sensors.base import SensorDocument, SensorQuery, content_hash  # noqa: E402
from northvaine.sensors.html_text import html_to_text  # noqa: E402
from northvaine.sensors.registry import get_sensor  # noqa: E402
from northvaine.sensors.replay import (  # noqa: E402
    ReplayMismatch,
    load_exchanges,
    replay_transport,
)

CLIENTS_DIR = ROOT / "tests" / "fixtures" / "clients"
SENSORS_DIR = ROOT / "tests" / "fixtures" / "sensors"
WEB_DIR = ROOT / "tests" / "fixtures" / "web"
OUT_DIR = ROOT / "tests" / "fixtures" / "llm" / "ledger"
REQUIRED_HEAD = "0005"
WEB_GROUP = "web"
WEB_URL_PREFIX = "https://fixtures.invalid/"
# The settings that shape request bodies; stored in each recording so replay can pin them.
SHAPING_SETTINGS = (
    "extract_max_doc_chars",
    "extract_max_claims",
    "extract_max_tokens",
    "support_max_tokens",
)
# A plan estimate, not a measurement: prompt overhead and the embeds a document may need.
PROMPT_OVERHEAD_CHARS = 2000
EMBEDS_PER_DOCUMENT = 8
EMBED_CHARS = 300

Head = Callable[[str], Awaitable[str]]
SessionFactory = Callable[[], AbstractAsyncContextManager[Any]]
ConceptLoader = Callable[[Any], Awaitable[list[Any]]]
BuildEvidence = Callable[..., Awaitable[Any]]
ClientFactory = Callable[[], Any]


class Refused(RuntimeError):  # noqa: N818 - a refusal, reported to the orchestrator
    """The recorder stopped on purpose (precondition, secret, email or phone)."""


@dataclass
class Group:
    name: str
    documents: list[EvidenceDocument] = field(default_factory=list)


_SIBLINGS: dict[str, ModuleType] = {}


def sibling(name: str) -> ModuleType:
    """A sibling script loaded by path (`scripts/` is not a package)."""
    if name not in _SIBLINGS:
        spec = importlib.util.spec_from_file_location(
            f"nv_sibling_{name}", ROOT / "scripts" / f"{name}.py"
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        _SIBLINGS[name] = module
    return _SIBLINGS[name]


# --- documents ----------------------------------------------------------------------------


def evidence_from_sensor(doc: SensorDocument) -> EvidenceDocument:
    from northvaine.radar.ledger import evidence_document_from_sensor

    return evidence_document_from_sensor(doc)


async def sensor_documents(
    spec: dict[str, Any], sensors_dir: Path = SENSORS_DIR
) -> list[EvidenceDocument]:
    """The documents a client's recorded sensor fixtures produce, replayed offline."""
    replay_settings = Settings(
        _env_file=None, ted_min_interval_seconds=0, tavily_api_key=SecretStr("replay-only")
    )
    docs: dict[Any, EvidenceDocument] = {}
    for name, queries in spec.get("sensors", {}).items():
        for number, raw in enumerate(queries, start=1):
            path = sensors_dir / name / f"{spec['id']}_{number}.json"
            if not path.exists():
                continue  # the recorder refused some Tavily responses; only recorded calls replay
            transport = replay_transport(load_exchanges(path))
            async with httpx.AsyncClient(transport=transport) as client:
                sensor = get_sensor(name, client=client, settings=replay_settings)
                try:
                    result = await sensor.search(SensorQuery.model_validate(raw))
                except ReplayMismatch:
                    continue
            for sensor_doc in result.documents:
                evidence = evidence_from_sensor(sensor_doc)
                docs.setdefault(evidence.id, evidence)
    return list(docs.values())


def web_documents(web_dir: Path = WEB_DIR) -> list[EvidenceDocument]:
    """`tests/fixtures/web/*.html` as `website` documents (title and text via `html_to_text`)."""
    from datetime import UTC, datetime

    from northvaine.sensors.website import WebsiteSensor

    fetched = datetime(2026, 10, 1, tzinfo=UTC)
    docs: list[EvidenceDocument] = []
    for path in sorted(web_dir.glob("*.html")):
        title, text = html_to_text(path.read_text(encoding="utf-8"))
        sensor_doc = SensorDocument(
            source=WebsiteSensor.name,
            tier=WebsiteSensor.tier,
            url=f"{WEB_URL_PREFIX}{path.name}",
            title=title,
            text=text,
            content_hash=content_hash(text),
            fetched_at=fetched,
            available_at=fetched,
        )
        docs.append(evidence_from_sensor(sensor_doc))
    return docs


def load_specs(folder: Path = CLIENTS_DIR, only: str | None = None) -> list[dict[str, Any]]:
    specs = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(folder.glob("*.json"))]
    return [s for s in specs if only in (None, s["id"])]


async def build_groups(
    *,
    clients_dir: Path = CLIENTS_DIR,
    sensors_dir: Path = SENSORS_DIR,
    web_dir: Path = WEB_DIR,
    only: str | None = None,
) -> list[Group]:
    groups = [
        Group(spec["id"], await sensor_documents(spec, sensors_dir))
        for spec in load_specs(clients_dir, only)
    ]
    if only in (None, WEB_GROUP):
        groups.append(Group(WEB_GROUP, web_documents(web_dir)))
    return groups


# --- plan ---------------------------------------------------------------------------------


def uses_llm(doc: EvidenceDocument, settings: Settings) -> bool:
    """Whether the source rule sends this document to the model (structured ones do not)."""
    rule = settings.evidence_source_rules.get(doc.source_name)
    if rule == "full_text":
        return True
    return rule == "raw_only" and doc.meta.get("text_kind") == "raw"


def _tokens(chars: int) -> int:
    return max(1, -(-chars // 3))  # the same deliberate over-estimate as llm.py


def estimate_document(doc: EvidenceDocument, settings: Settings) -> tuple[int, Decimal | None]:
    """(calls, upper-bound cost) for one document; cost is None when a model has no price."""
    if not uses_llm(doc, settings):
        return 0, Decimal("0")
    calls = 2 + EMBEDS_PER_DOCUMENT
    text_chars = min(len(doc.text), settings.extract_max_doc_chars)
    try:
        if not (settings.model_fast and settings.model_embed):
            return calls, None
        cost = (
            estimate_cost(
                settings.model_fast,
                _tokens(text_chars + PROMPT_OVERHEAD_CHARS),
                settings.extract_max_tokens,
            )
            + estimate_cost(
                settings.model_fast,
                _tokens(PROMPT_OVERHEAD_CHARS * 2),
                settings.support_max_tokens,
            )
            + EMBEDS_PER_DOCUMENT * estimate_cost(settings.model_embed, _tokens(EMBED_CHARS), 0)
        )
    except Exception:  # an unknown model id: say so instead of guessing a price
        return calls, None
    return calls, cost


def print_plan(groups: list[Group], settings: Settings) -> None:
    print("LLM fixture recording plan (nothing is called without --yes)")
    total_calls, total_cost, known = 0, Decimal("0"), True
    for group in groups:
        calls, cost, llm_docs, priced = 0, Decimal("0"), 0, True
        for doc in group.documents:
            doc_calls, doc_cost = estimate_document(doc, settings)
            calls += doc_calls
            llm_docs += doc_calls > 0
            if doc_cost is None:
                known = priced = False
            else:
                cost += doc_cost
        total_calls += calls
        total_cost += cost
        print(
            f"  {group.name:24} documents={len(group.documents):3} "
            f"sent to the model={llm_docs:2} estimated calls<={calls:3} "
            f"cost<={f'${cost:.4f}' if priced else 'unknown'}"
        )
    shown = (
        f"${total_cost:.4f}" if known else "unknown (MODEL_FAST / MODEL_EMBED unset or unpriced)"
    )
    print(f"  total: estimated calls<={total_calls}, estimated cost<={shown}")


# --- redaction ----------------------------------------------------------------------------


def _secrets_in_use() -> tuple[str, ...]:
    return tuple(s for s in sibling("smoke_llm").known_secrets() if s)


def problems_in(value: Any, secrets: tuple[str, ...], where: str) -> list[str]:
    """Where `value` holds a secret-shaped string, an email address or a phone number."""
    smoke, sensors = sibling("smoke_llm"), sibling("record_sensor_fixtures")
    found: list[str] = []
    if smoke.redact(value, secrets) != value:
        found.append(f"{where}: a secret-shaped value")
    found.extend(f"{where}: email or phone at {path}" for path in sensors.find_pii(value))
    return found


def preflight(groups: list[Group], settings: Settings) -> list[str]:
    """Check the text that will be sent, before any money is spent."""
    secrets = _secrets_in_use()
    problems: list[str] = []
    for group in groups:
        for doc in group.documents:
            if uses_llm(doc, settings):
                problems += problems_in(doc.text, secrets, f"{group.name} {doc.url}")
    return problems


def redact_recording(recording: LlmRecording) -> LlmRecording:
    """The recording after `smoke_llm.redact`; raises `Refused` if anything survives.

    A request that redaction would change is refused rather than rewritten: its key is the
    hash of the exact request, so an edited request could never be replayed.
    """
    smoke, secrets = sibling("smoke_llm"), _secrets_in_use()
    problems: list[str] = []
    exchanges: list[LlmExchange] = []
    for index, ex in enumerate(recording.exchanges):
        where = f"exchange {index} ({ex.prompt_version or ex.kind})"
        problems += problems_in(ex.request, secrets, f"{where} request")
        response = smoke.redact(ex.response, secrets)
        problems += problems_in(response, secrets, f"{where} response")
        exchanges.append(ex.model_copy(update={"response": response}))
    meta = smoke.redact({"models": recording.models, "settings": recording.settings}, secrets)
    if problems:
        raise Refused("REFUSED to write, nothing was written:\n  " + "\n  ".join(problems[:10]))
    return recording.model_copy(
        update={"exchanges": exchanges, "models": meta["models"], "settings": meta["settings"]}
    )


# --- recording ----------------------------------------------------------------------------


def models_of(settings: Settings) -> dict[str, str]:
    tiers = {
        "fast": settings.model_fast,
        "mid": settings.model_mid,
        "deep": settings.model_deep,
        "embed": settings.model_embed,
    }
    return {tier: model for tier, model in tiers.items() if model}


async def record_group(
    group: Group,
    *,
    settings: Settings,
    session: Any,
    concepts: list[Any],
    build_evidence: BuildEvidence,
    real_client: Any,
) -> LlmRecording:
    recorder = RecordingClient(real_client)
    run = RunContext()
    with llm.client_override(recorder):
        for doc in group.documents:
            await build_evidence(doc, concepts, [], run=run, session=session)
    shaping = {name: getattr(settings, name) for name in SHAPING_SETTINGS}
    return recorder.recording(models=models_of(settings), settings=shaping)


def check_preconditions(settings: Settings) -> str:
    """The database URL, after checking the budget caps, the models and the config."""
    for name, value in (
        ("DAILY_BUDGET_USD", settings.daily_budget_usd),
        ("TOTAL_BUDGET_USD", settings.total_budget_usd),
    ):
        if value is None:
            raise Refused(f"{name} is not set. Set it in .env before recording.")
    for name, value in (("MODEL_FAST", settings.model_fast), ("MODEL_EMBED", settings.model_embed)):
        if not value:
            raise Refused(f"{name} is not set. Set it in .env before recording.")
    try:
        validate_configured_models(settings)
    except ConfigError as error:
        raise Refused(str(error)) from error
    if settings.database_url is None:
        raise Refused("DATABASE_URL is not set; llm_calls has nowhere to be written.")
    return settings.database_url.get_secret_value()


async def run_recording(
    groups: list[Group],
    settings: Settings,
    *,
    url: str,
    head: Head,
    session_factory: SessionFactory,
    load_concepts: ConceptLoader,
    build_evidence: BuildEvidence,
    client_factory: ClientFactory,
    out_dir: Path,
) -> int:
    found = await head(url)
    if found != REQUIRED_HEAD:
        raise Refused(
            f"the database is at alembic head {found!r}, but recording needs {REQUIRED_HEAD!r}. "
            "Run `uv run python scripts/tasks.py migrate` first."
        )
    problems = preflight(groups, settings)
    if problems:
        raise Refused("REFUSED before spending anything:\n  " + "\n  ".join(problems[:10]))
    real_client = client_factory()
    recorded: list[tuple[str, LlmRecording]] = []
    async with session_factory() as session:
        concepts = await load_concepts(session)
        for group in groups:
            print(f"recording {group.name} ({len(group.documents)} documents)")
            recording = await record_group(
                group,
                settings=settings,
                session=session,
                concepts=concepts,
                build_evidence=build_evidence,
                real_client=real_client,
            )
            recorded.append((group.name, recording))
    cleaned = [(name, redact_recording(recording)) for name, recording in recorded]
    for name, recording in cleaned:
        save_recording(out_dir / f"{name}.json", recording)
        print(f"wrote {name}.json ({len(recording.exchanges)} exchanges)")
    print("Read every new recording by eye before committing. Never hand-edit one.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="record_llm_fixtures.py",
        description="Record redacted LLM fixtures for the evidence ledger (spends money).",
    )
    parser.add_argument("--yes", action="store_true", help="actually call the live API")
    parser.add_argument("--client", help="record only this client id (or 'web')")
    return parser


def main(
    argv: list[str] | None = None,
    *,
    clients_dir: Path = CLIENTS_DIR,
    sensors_dir: Path = SENSORS_DIR,
    web_dir: Path = WEB_DIR,
    out_dir: Path = OUT_DIR,
    settings: Settings | None = None,
    head: Head | None = None,
    session_factory: SessionFactory | None = None,
    load_concepts: ConceptLoader | None = None,
    build_evidence: BuildEvidence | None = None,
    client_factory: ClientFactory | None = None,
) -> int:
    args = build_parser().parse_args(argv)
    settings = settings or get_settings()
    groups = asyncio.run(
        build_groups(
            clients_dir=clients_dir, sensors_dir=sensors_dir, web_dir=web_dir, only=args.client
        )
    )
    if not args.yes:
        print_plan(groups, settings)
        print("\nNothing was called. Re-run with --yes to record.", file=sys.stderr)
        return 0
    try:
        url = check_preconditions(settings)
        if build_evidence is None:
            from northvaine.radar.ledger import build_evidence as default_build

            build_evidence = default_build
        if load_concepts is None:
            from northvaine.core.ledger import load_concepts as default_load

            load_concepts = default_load
        if session_factory is None:
            from northvaine.core.db import session_scope

            session_factory = session_scope
        return asyncio.run(
            run_recording(
                groups,
                settings,
                url=url,
                head=head or sibling("smoke_llm").alembic_head,
                session_factory=session_factory,
                load_concepts=load_concepts,
                build_evidence=build_evidence,
                client_factory=client_factory or llm.get_client,
                out_dir=out_dir,
            )
        )
    except Refused as refusal:
        print(str(refusal), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
