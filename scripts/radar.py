"""Run the radar for one client: offline from a recording (default) or live (orchestrator only).

Replay (default) reads `tests/fixtures/radar/<client>/{meta,http,pages,llm}.json`, needs no `.env`
and no network, and writes the brief, scorecard and run record under `reports/radar/`.

`--record --yes` runs the same pipeline live: sensors through `RecordingTransport`, publisher pages
through `LivePageFetcher`, the model through `RecordingClient`. It spends Tavily credits and a few
cents of model calls, refuses without both budget caps, prints a plan and stops without `--yes`,
redacts everything, and refuses to write if an email address, a phone number or a secret survives.

Run it with:
  uv run python scripts/tasks.py radar -- --client stone_supplier
  uv run python scripts/tasks.py record-radar -- --client stone_supplier --yes   (orchestrator)
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import ModuleType
from typing import Any

import httpx
from pydantic import Field, SecretStr

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:  # run as a plain script: make `northvaine` importable
    sys.path.insert(0, str(ROOT))

from northvaine.brain import llm  # noqa: E402
from northvaine.brain.budget import RunContext  # noqa: E402
from northvaine.brain.errors import ConfigError  # noqa: E402
from northvaine.brain.pricing import estimate_cost, validate_configured_models  # noqa: E402
from northvaine.brain.replay import (  # noqa: E402
    LlmRecording,
    RecordingClient,
    ReplayClient,
    load_recording,
    replay_environment,
    save_recording,
)
from northvaine.core.models import NorthvaineModel  # noqa: E402
from northvaine.core.settings import Settings, get_settings  # noqa: E402
from northvaine.radar.brief import write_reports  # noqa: E402
from northvaine.radar.discover import (  # noqa: E402
    LivePageFetcher,
    PageFetcher,
    RecordedPageFetcher,
    prepare_queries,
    strip_contacts,
)
from northvaine.radar.models import (  # noqa: E402
    ClientSpec,
    RadarRun,
    RejectedAs,
    UpgradedPage,
    load_client_spec,
)
from northvaine.radar.run import run_radar, seeded_concepts  # noqa: E402
from northvaine.sensors.base import SensorQuery  # noqa: E402
from northvaine.sensors.fts import FTS_API_URL  # noqa: E402
from northvaine.sensors.fts import _text as fts_text  # noqa: E402
from northvaine.sensors.replay import (  # noqa: E402
    RecordedExchange,
    RecordingTransport,
    load_exchanges,
    replay_transport,
    save_exchanges,
)
from northvaine.sensors.ted import withhold_natural_persons  # noqa: E402

META, HTTP, PAGES, LLM = "meta.json", "http.json", "pages.json", "llm.json"
FILES = (META, HTTP, PAGES, LLM)
# The settings that shape request bodies; stored in llm.json so replay can pin them.
SHAPING_SETTINGS = (
    "extract_max_doc_chars",
    "extract_max_claims",
    "extract_max_tokens",
    "support_max_tokens",
    "gate_max_tokens",
    "skeptic_max_tokens",
    "radar_tender_lookback_days",  # the query focus (D71) is part of what was sent
    "radar_enumerable_max_results",
    "radar_bidder_lookback_days",  # likely-bidder searches (D81) are part of what was sent
    "radar_bidder_max",
    "radar_bidder_max_queries",
    "radar_bidder_max_codes",
    "radar_bidder_max_results",
    "radar_fit_max_accounts",  # company-fit searches and page fetches (D96) too
    "radar_fit_pages",
    "radar_fit_about_pages",
    "radar_fit_quotes",
    "radar_fit_min_token",
    "hmrc_min_kept",  # how many importers were kept, gated and looked up (D107)
    "radar_max_gate_candidates",
    "radar_register_max_lookups",
    "radar_seed_max_lookups",  # D109
    "radar_timing_max_lookups",  # D111
    "radar_site_guess_max_companies",  # D113
    "radar_site_guess_per_company",
    "radar_fit_single_search",  # D108
    "radar_link_by_register",  # D115
    "radar_register_accounts_type",  # D116
    "radar_investigate_top",  # D117
    "radar_fit_distinctive",  # D118
    "radar_fit_common_share",
    "radar_fit_deep_pages",  # D119
    "radar_fit_deep_path_words",
    "radar_fit_judge_top",
    "radar_fit_judge_chars",
    "radar_fit_judge_role",  # D120
    "radar_fit_judge_brands",  # D121
    "radar_investigate_max_searches",
    "fit_contact_role_words",
)
# A plan estimate, not a measurement (PLAN.md cost table): tokens per call.
GATE_TOKENS = (2000, 300)
EXTRACT_TOKENS = (4000, 800)
EMBEDS_PER_DOCUMENT = 8

ClientFactory = Callable[[], Any]
FetcherFactory = Callable[[Settings], PageFetcher]


class Refused(RuntimeError):  # noqa: N818 - a refusal, reported to the orchestrator
    """The command stopped on purpose (missing recording, precondition, email, phone, secret)."""


class RadarMeta(NorthvaineModel):
    client: str
    as_of: datetime
    recorded_at: str
    queries: dict[str, list[SensorQuery]]
    seeds: list[str] = Field(default_factory=list)  # D109: approved leads seeding this run


class RecordingPageFetcher:
    """Wraps the live fetcher and keeps every page it returns, so pages fetched after discovery
    (company fit, D96) replay too, not only the upgraded leads."""

    def __init__(self, inner: PageFetcher) -> None:
        self._inner = inner
        self.pages: list[UpgradedPage] = []

    async def fetch(self, url: str) -> UpgradedPage:
        page = await self._inner.fetch(url)
        self.pages.append(page)
        return page


@dataclass
class Recording:
    meta: RadarMeta
    exchanges: list[RecordedExchange]
    pages: list[UpgradedPage]
    llm: LlmRecording


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


def resolve(path: str | Path, root: Path = ROOT) -> Path:
    p = Path(path)
    return p if p.is_absolute() else root / p


# --- recording files ----------------------------------------------------------------------


def load_replay(folder: Path, client: str) -> Recording:
    """The four recording files of one client; `Refused` names the missing ones."""
    missing = [name for name in FILES if not (folder / name).is_file()]
    if missing:
        raise Refused(
            f"no radar recording for client {client!r} in {folder} (missing {', '.join(missing)}). "
            f"Record it with `uv run python scripts/tasks.py record-radar -- --client {client} "
            "--yes` (orchestrator only)."
        )
    return Recording(
        meta=RadarMeta.model_validate_json((folder / META).read_text(encoding="utf-8")),
        exchanges=load_exchanges(folder / HTTP),
        pages=[
            UpgradedPage.model_validate(p)
            for p in json.loads((folder / PAGES).read_text(encoding="utf-8"))
        ],
        llm=load_recording(folder / LLM),
    )


def write_recording(folder: Path, recording: Recording) -> list[Path]:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / META).write_text(
        json.dumps(recording.meta.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    save_exchanges(folder / HTTP, recording.exchanges)
    (folder / PAGES).write_text(
        json.dumps(
            [p.model_dump(mode="json") for p in recording.pages], indent=2, ensure_ascii=False
        )
        + "\n",
        encoding="utf-8",
    )
    save_recording(folder / LLM, recording.llm)
    return [folder / name for name in FILES]


# --- replay -------------------------------------------------------------------------------


async def run_replay(
    spec: ClientSpec, recording: Recording, *, evidence_out: list[Any] | None = None
) -> RadarRun:
    """The whole pipeline on recorded HTTP, pages and model replies; no `.env`, no network."""
    as_of = recording.meta.as_of
    with replay_environment(recording.llm):
        # Inside the pinned environment, so the query focus settings are the recorded ones.
        base = Settings(_env_file=None)
        # The register check runs on replay only when the live run made register lookups, so
        # recordings from before it (D103) replay exactly as they were made.
        register_url = base.companies_house_api_url.rstrip("/")
        had_register = any(ex.url.startswith(register_url) for ex in recording.exchanges)
        settings = Settings(
            _env_file=None,
            ted_min_interval_seconds=0,
            companies_house_min_interval_seconds=0,
            tavily_api_key=SecretStr("replay-only"),
            companies_house_api_key=SecretStr("replay-only") if had_register else None,
        )
        if prepare_queries(spec.sensors, as_of.date(), settings) != recording.meta.queries:
            raise Refused(
                f"the client spec {spec.id!r} no longer matches its recording (queries differ). "
                "Re-record it with record-radar."
            )
        transport = replay_transport(recording.exchanges)
        async with httpx.AsyncClient(transport=transport) as client:
            with llm.client_override(ReplayClient(recording.llm)):
                return await run_radar(
                    spec,
                    as_of=as_of,
                    http=client,
                    fetcher=RecordedPageFetcher(recording.pages),
                    concepts=seeded_concepts(),
                    run=RunContext(),
                    settings=settings,
                    evidence_out=evidence_out,
                    seeds=recording.meta.seeds,
                )


async def save_run(run: RadarRun, evidence: list[Any], session_factory: Any = None) -> None:
    """Save a finished run into the database (D86); prints what was stored."""
    from northvaine.radar.persist import persist_run

    if session_factory is None:
        from northvaine.core.db import session_scope

        session_factory = session_scope
    async with session_factory() as session:
        saved = await persist_run(session, run, evidence)
    print(
        f"saved: {saved.documents_inserted} new document(s), {saved.claims} claim(s), "
        f"{saved.companies} compan(ies), {len(saved.cases)} case(s), "
        f"{saved.decisions} decision(s)"
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


def _cost(model: str | None, tokens: tuple[int, int], calls: int) -> Decimal | None:
    if not model:
        return None
    try:
        return estimate_cost(model, tokens[0], tokens[1]) * calls
    except Exception:  # an unknown model id: say so instead of guessing a price
        return None


def print_plan(spec: ClientSpec, as_of: datetime, settings: Settings) -> None:
    queries = prepare_queries(spec.sensors, as_of.date(), settings)
    uploads = settings.radar_max_lead_upgrades
    gates = settings.radar_max_gate_candidates
    docs = uploads + 5  # upgraded pages plus a few full-text snippets: a plan, not a measurement
    print(f"Radar recording plan for {spec.id} (nothing is called without --yes)")
    print(f"  as_of {as_of.isoformat(timespec='seconds')}; query dates shifted to end there")
    for sensor, items in queries.items():
        print(f"  sensor {sensor}: {len(items)} query(ies)")
    tavily = len(queries.get("tavily", []))
    print(f"  Tavily credits: about {tavily} (cap {settings.tavily_max_calls_per_run} per run)")
    print(f"  publisher page fetches: up to {uploads} (robots.txt and the deny list apply)")
    print(f"  model calls: up to {2 * docs} extract/support (fast), {docs * EMBEDS_PER_DOCUMENT}")
    print(f"    embeds, {gates} gate and {gates} skeptic (mid)")
    parts = [
        _cost(settings.model_fast, EXTRACT_TOKENS, 2 * docs),
        _cost(settings.model_mid, GATE_TOKENS, 2 * gates),
    ]
    total = "unknown (MODEL_FAST / MODEL_MID unset or unpriced)"
    if all(p is not None for p in parts):
        total = f"${sum(p for p in parts if p is not None):.4f}"
    print(f"  estimated model cost, upper bound: {total}")
    print(f"  run cap: ${settings.radar_run_budget_usd} (radar_run_budget_usd)")
    print("  every model call writes an llm_calls row (DATABASE_URL) and is held to the per-call,")
    print("  per-run, per-day and lifetime caps of llm.py")


def check_preconditions(spec: ClientSpec, settings: Settings) -> None:
    for name, value in (
        ("DAILY_BUDGET_USD", settings.daily_budget_usd),
        ("TOTAL_BUDGET_USD", settings.total_budget_usd),
    ):
        if value is None:
            raise Refused(f"{name} is not set. Set it in .env before recording.")
    for name, value in (
        ("MODEL_FAST", settings.model_fast),
        ("MODEL_MID", settings.model_mid),
        ("MODEL_EMBED", settings.model_embed),
    ):
        if not value:
            raise Refused(f"{name} is not set. Set it in .env before recording.")
    try:
        validate_configured_models(settings)
    except ConfigError as error:
        raise Refused(str(error)) from error
    if spec.sensors.get("tavily") and settings.tavily_api_key is None:
        raise Refused("TAVILY_API_KEY is not set. Set it in .env before recording.")


def _secrets(settings: Settings) -> tuple[str, ...]:
    found = list(sibling("smoke_llm").known_secrets())
    if settings.tavily_api_key is not None:
        found.append(settings.tavily_api_key.get_secret_value())
    return tuple(s for s in found if s)


def _strip_search_contacts(ex: Any, tavily_prefix: str) -> Any:
    """Strip contacts from search-result text with the pipeline's own `strip_contacts`, so the
    replayed documents are byte-identical to what the live run fed the model (discover strips
    the same fields before any model call)."""
    body = ex.body_json
    if not ex.url.startswith(tavily_prefix) or not isinstance(body, dict):
        return ex
    results = []
    for result in body.get("results") or []:
        if isinstance(result, dict):
            result = {
                k: strip_contacts(v)
                if k in ("title", "content", "raw_content") and isinstance(v, str)
                else v
                for k, v in result.items()
            }
        results.append(result)
    return ex.model_copy(update={"body_json": {**body, "results": results}})


# The OCDS paths sensors/fts.py reads; everything else (free text, contact points, amendments,
# terms) is dropped before a recording is saved. `{}` keeps a whole value.
_FTS_READ: dict[str, Any] = {
    "ocid": {}, "id": {}, "tag": {}, "date": {}, "language": {},
    "buyer": {"id": {}, "name": {}},
    "parties": {"id": {}, "address": {"country": {}}},
    "tender": {
        "title": {}, "classification": {}, "mainProcurementCategory": {},
        "items": {"additionalClassifications": {}},
        "lots": {"value": {}}, "value": {}, "tenderPeriod": {"endDate": {}},
        "documents": {"id": {}, "noticeType": {}}, "legalBasis": {"id": {}},
        "aboveThreshold": {},
    },
    "awards": {
        "suppliers": {"id": {}, "name": {}},
        "items": {"additionalClassifications": {}},
        "additionalClassifications": {},
    },
    "contracts": {
        "title": {}, "value": {}, "dateSigned": {}, "documents": {"id": {}, "noticeType": {}},
    },
}  # fmt: skip


def _project(value: Any, shape: dict[str, Any]) -> Any:
    if not shape:
        # read text goes through the sensor's own cleaning (emails and phones removed), which
        # is idempotent, so replay parses exactly what the live run parsed
        if isinstance(value, str) and value.strip():
            return fts_text(value)
        return value
    if isinstance(value, list):
        return [_project(v, shape) for v in value]
    if isinstance(value, dict):
        return {k: _project(v, shape[k]) for k, v in value.items() if k in shape}
    return value


# Persons with significant control: only companies are named (sensors/companies_house). For a
# person the recording keeps the kind and dates the parser reads, never a name, birth date,
# nationality or address.
_PSC_PERSON_KEYS = ("kind", "notified_on", "ceased_on", "ceased")


def _strip_register_people(ex: Any, register_prefix: str) -> Any:
    body = ex.body_json
    if not ex.url.startswith(register_prefix) or not isinstance(body, dict):
        return ex
    items = body.get("items")
    if "persons-with-significant-control" not in ex.url or not isinstance(items, list):
        return ex
    kept = []
    for item in items:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind") or "")
        if kind.startswith(("corporate-entity", "legal-person")):
            kept.append({k: item[k] for k in (*_PSC_PERSON_KEYS, "name") if k in item})
        else:
            kept.append({k: item[k] for k in _PSC_PERSON_KEYS if k in item})
    return ex.model_copy(update={"body_json": {"items": kept}})


def _strip_fts_unread(ex: Any) -> Any:
    """FTS releases reduced to the fields the sensor reads: nothing else is ever saved."""
    body = ex.body_json
    if not ex.url.startswith(FTS_API_URL) or not isinstance(body, dict):
        return ex
    releases = body.get("releases")
    if not isinstance(releases, list):
        return ex
    kept = [_project(r, _FTS_READ) for r in releases]
    return ex.model_copy(update={"body_json": {**body, "releases": kept}})


def _withhold_ted_persons(ex: Any, tavily_prefix: str, settings: Settings) -> Any:
    """Withhold natural-person names in TED notices with the sensor's own function, so the
    replayed documents are identical to what the live run parsed (D76)."""
    body = ex.body_json
    if ex.url.startswith(tavily_prefix) or not isinstance(body, dict):
        return ex
    notices = body.get("notices")
    if not isinstance(notices, list):
        return ex
    cleaned = [withhold_natural_persons(n, settings) if isinstance(n, dict) else n for n in notices]
    return ex.model_copy(update={"body_json": {**body, "notices": cleaned}})


def redact_recording(recording: Recording, settings: Settings) -> Recording:
    """The recording after the sensor and LLM redaction rules; `Refused` if anything survives."""
    sensors, llm_script = sibling("record_sensor_fixtures"), sibling("record_llm_fixtures")
    secrets = _secrets(settings)
    tavily_prefix = settings.tavily_api_url.rstrip("/")
    exchanges = [
        sensors.redact_exchange(
            sensors.trim_exchange(
                ex, "tavily" if ex.url.startswith(tavily_prefix) else "ted", 10**6
            ),
            secrets=secrets,
        )
        for ex in recording.exchanges
    ]
    exchanges = [_strip_search_contacts(ex, tavily_prefix) for ex in exchanges]
    exchanges = [_strip_fts_unread(ex) for ex in exchanges]
    register_prefix = settings.companies_house_api_url.rstrip("/")
    exchanges = [_strip_register_people(ex, register_prefix) for ex in exchanges]
    exchanges = [_withhold_ted_persons(ex, tavily_prefix, settings) for ex in exchanges]
    problems = sensors.find_pii([e.model_dump(mode="json") for e in exchanges], "http")
    problems += sensors.find_pii([p.model_dump(mode="json") for p in recording.pages], "pages")
    problems += sensors.find_pii(recording.meta.model_dump(mode="json"), "meta")
    if problems:
        raise Refused(
            "REFUSED to write, nothing was written (email or phone survives):\n  "
            + "\n  ".join(problems[:10])
        )
    try:
        cleaned = llm_script.redact_recording(recording.llm)
    except llm_script.Refused as refusal:
        raise Refused(str(refusal)) from refusal
    return Recording(recording.meta, exchanges, recording.pages, cleaned)


async def run_record(
    spec: ClientSpec,
    as_of: datetime,
    settings: Settings,
    *,
    inner_transport: httpx.AsyncBaseTransport | None = None,
    client_factory: ClientFactory | None = None,
    fetcher_factory: FetcherFactory | None = None,
    session_factory: Any = None,
    save: bool = False,
    strategy: Any = None,
    seeds: list[str] | None = None,
) -> tuple[RadarRun, Recording]:
    """The live run, with every HTTP exchange and model exchange recorded (not yet redacted)."""
    evidence: list[Any] = []
    http_recorder = RecordingTransport(inner_transport or httpx.AsyncHTTPTransport())
    llm_recorder = RecordingClient((client_factory or llm.get_client)())
    fetcher = RecordingPageFetcher(
        (fetcher_factory or (lambda s: LivePageFetcher(settings=s)))(settings)
    )
    commit_each_call = session_factory is None  # the live ledger commits row by row (D107)
    if session_factory is None:
        # A live run writes an llm_calls row per call and is held to the daily and lifetime
        # caps, like every other live model call (CLAUDE.md #8).
        from northvaine.core.db import session_scope

        session_factory = session_scope
    async with (
        httpx.AsyncClient(transport=http_recorder, timeout=60.0) as client,
        session_factory() as session,
    ):
        with llm.client_override(llm_recorder):
            run = await run_radar(
                spec,
                as_of=as_of,
                http=client,
                fetcher=fetcher,
                concepts=seeded_concepts(),
                run=RunContext(commit_each_call=commit_each_call),
                settings=settings,
                session=session,
                evidence_out=evidence,
                strategy=strategy,
                seeds=seeds,
            )
        if save:
            from northvaine.radar.persist import persist_run

            saved = await persist_run(session, run, evidence)
            print(f"saved: {len(saved.cases)} case(s), {saved.decisions} decision(s)")
    meta = RadarMeta(
        client=spec.id,
        as_of=as_of,
        recorded_at=datetime.now(UTC).isoformat(timespec="seconds"),
        queries=run.queries,
        seeds=list(seeds or []),
    )
    shaping = {name: getattr(settings, name) for name in SHAPING_SETTINGS}
    recording = Recording(
        meta=meta,
        exchanges=list(http_recorder.exchanges),
        pages=_all_pages(run.upgraded, fetcher.pages),
        llm=llm_recorder.recording(models=models_of(settings), settings=shaping),
    )
    return run, recording


def _all_pages(upgraded: list[UpgradedPage], fetched: list[UpgradedPage]) -> list[UpgradedPage]:
    """The upgraded leads, then any other fetched page, once per lead URL."""
    pages = list(upgraded)
    seen = {p.lead_url for p in pages}
    for page in fetched:
        if page.lead_url not in seen:
            seen.add(page.lead_url)
            pages.append(page)
    return pages


# --- reporting ----------------------------------------------------------------------------


def summary_lines(run: RadarRun) -> list[str]:
    by_kind = ", ".join(f"{k} {n}" for k, n in run.documents_by_kind.items()) or "none"
    fetched = sum(1 for p in run.upgraded if p.refused is None)
    reasons: dict[str, int] = {}
    for item in run.rejected:
        why = (item.gate.rejected_as or RejectedAs.UNIDENTIFIED).value
        reasons[why] = reasons.get(why, 0) + 1
    rejected = ", ".join(f"{k} {n}" for k, n in sorted(reasons.items())) or "none"
    return [
        f"documents: {sum(run.documents_by_kind.values())} ({by_kind})",
        f"leads: {run.leads}",
        f"upgraded: {fetched} fetched of {len(run.upgraded)} tried",
        f"candidates: {len(run.entries) + len(run.rejected)}",
        f"rejected: {len(run.rejected)} ({rejected})",
        f"briefed: {len(run.entries)}",
        f"model calls: {run.llm_calls}, cost ${run.cost_usd:.4f}",
        *[f"note: {n}" for n in run.notes],
    ]


def report(run: RadarRun, out_dir: Path) -> list[Path]:
    paths = write_reports(run, out_dir)
    for line in summary_lines(run):
        print(line)
    for path in paths:
        print(f"wrote {path}")
    return paths


# --- command line -------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="radar.py",
        description="Run the radar for one client: replay a recording (default) or --record live.",
    )
    parser.add_argument("--client", required=True, help="client id (a file in the clients dir)")
    parser.add_argument("--out", help="reports folder (default: settings.radar_reports_dir)")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--replay", action="store_true", help="offline from a recording (default)")
    mode.add_argument("--record", action="store_true", help="live run that records (SPENDS MONEY)")
    parser.add_argument("--yes", action="store_true", help="with --record: actually call the APIs")
    parser.add_argument("--as-of", help="with --record: run date YYYY-MM-DD (default: now, UTC)")
    parser.add_argument(
        "--save", action="store_true", help="also save the run into the database (DATABASE_URL)"
    )
    parser.add_argument("--fixtures-dir", help="recordings folder (default: settings)")
    parser.add_argument("--clients-dir", help="client specs folder (default: settings)")
    return parser


def _as_of(text: str | None) -> datetime:
    if text is None:
        return datetime.now(UTC).replace(microsecond=0)
    return datetime.fromisoformat(text).replace(tzinfo=UTC)


def main(
    argv: list[str] | None = None,
    *,
    root: Path = ROOT,
    settings: Settings | None = None,
    inner_transport: httpx.AsyncBaseTransport | None = None,
    client_factory: ClientFactory | None = None,
    fetcher_factory: FetcherFactory | None = None,
    session_factory: Any = None,
) -> int:
    args = build_parser().parse_args(argv)
    if args.yes and not args.record:
        print("--yes only applies to --record", file=sys.stderr)
        return 2
    if args.as_of and not args.record:
        print("--as-of only applies to --record (a replay uses its recorded date)", file=sys.stderr)
        return 2
    try:
        base = settings or (get_settings() if args.record else Settings(_env_file=None))
        clients_dir = resolve(args.clients_dir or base.radar_clients_dir, root)
        fixtures = resolve(args.fixtures_dir or base.radar_fixtures_dir, root)
        out_dir = resolve(args.out or base.radar_reports_dir, root)
        try:
            spec = load_client_spec(args.client, clients_dir)
        except FileNotFoundError as error:
            raise Refused(str(error)) from error
        folder = fixtures / args.client
        if not args.record:
            evidence: list[Any] = []
            run = asyncio.run(
                run_replay(spec, load_replay(folder, args.client), evidence_out=evidence)
            )
            report(run, out_dir)
            if args.save:
                asyncio.run(save_run(run, evidence, session_factory))
            return 0
        as_of = _as_of(args.as_of)
        if not args.yes:
            print_plan(spec, as_of, base)
            print("\nNothing was called. Re-run with --yes to record.", file=sys.stderr)
            return 1
        check_preconditions(spec, base)
        # The owner's saved answers choose this run's searches once there are enough (D100).
        from northvaine.api.store import approved_leads, client_learning

        learned = client_learning(out_dir, args.client, base)
        seeds = approved_leads(out_dir, args.client)  # D109
        print(
            f"learning: {learned.labels:.0f} of {learned.needed:.0f} answers needed "
            + ("(the answers choose this run's searches)" if learned.active else "(not yet)")
        )
        run, recording = asyncio.run(
            run_record(
                spec,
                as_of,
                base,
                inner_transport=inner_transport,
                client_factory=client_factory,
                fetcher_factory=fetcher_factory,
                session_factory=session_factory,
                save=args.save,
                strategy=learned.strategy,
                seeds=seeds,
            )
        )
        clean = redact_recording(recording, base)
        for path in write_recording(folder, clean):
            print(f"wrote {path}")
        report(run, out_dir)
        print("Read the pages and the brief by eye before committing. Never hand-edit a recording.")
        return 0
    except Refused as refusal:
        print(str(refusal), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
