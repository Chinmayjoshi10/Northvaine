"""One radar run per client (T5.6): discover, extract, identify, gate, skeptic, rank.

The order is fixed here, in one function (rules #3 and #4): discover -> evidence ledger ->
candidates -> gate -> skeptic (passed candidates only, after their gate) -> rank. Nothing in this
module knows about a client or an industry: everything comes from the `ClientSpec` and settings.
"""

from __future__ import annotations

import asyncio
import importlib.util
import math
import random
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from northvaine.brain.budget import RunContext
from northvaine.brain.errors import (
    BudgetExceeded,
    LlmInvalidOutput,
    LlmTimeout,
    LlmTransportError,
)
from northvaine.core.models import (
    ConceptStatus,
    EventConceptRow,
    EvidenceDocument,
    LedgerResult,
)
from northvaine.core.settings import Settings, get_settings
from northvaine.radar.bidders import likely_bidders
from northvaine.radar.brief import main_selection, rank
from northvaine.radar.court import skeptic
from northvaine.radar.discover import PageFetcher, discover, prepare_queries
from northvaine.radar.edition import label_entries
from northvaine.radar.entities import build_candidates, company_key
from northvaine.radar.fit import company_fit
from northvaine.radar.gate import gate_candidate
from northvaine.radar.learning import Beta, choose_queries, exploration_pick, query_keys_by_ref
from northvaine.radar.ledger import build_evidence
from northvaine.radar.models import (
    Candidate,
    ClientSpec,
    GateDecision,
    RadarRun,
    RadarStream,
    RejectedEntry,
    SkepticFinding,
)
from northvaine.radar.register import register_check

__all__ = ["run_radar", "seeded_concepts"]

# One document or candidate the model could not answer is a note, not a failed run (D73).
# A replay mismatch is an AssertionError and is never caught here.
_ITEM_FAILURES = (LlmInvalidOutput, LlmTimeout, LlmTransportError)

MIGRATIONS = Path(__file__).resolve().parents[2] / "migrations" / "versions"
# Migrations that seed level-0 concepts, each with a `_SEED` of (label, description) pairs.
SEED_MIGRATIONS = ("0002_architecture_v2.py", "0007_trade_records_concept.py")
SEED_CREATED_AT = datetime(2026, 1, 1, tzinfo=UTC)


def _seed_pairs() -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for name in SEED_MIGRATIONS:
        path = MIGRATIONS / name
        spec = importlib.util.spec_from_file_location(f"nv_migration_{path.stem}", path)
        if spec is None or spec.loader is None:
            raise FileNotFoundError(f"cannot load {path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        pairs.extend(module._SEED)
    return pairs


def seeded_concepts() -> list[EventConceptRow]:
    """The level-0 event concepts seeded by the migrations, in `load_concepts` order
    (level, label). Read from the migrations so no label is typed here."""
    return [
        EventConceptRow(
            id=uuid5(NAMESPACE_URL, f"northvaine:concept:0:{label}"),
            parent_id=None,
            level=0,
            label=label,
            description=description,
            embedding=None,
            status=ConceptStatus.ACTIVE,
            merged_into=None,
            created_at=SEED_CREATED_AT,
        )
        for label, description in sorted(_seed_pairs())
    ]


def _gate_order(candidates: list[Candidate], today: date) -> list[Candidate]:
    """Open tender windows first (a seller can still bid), then proven buyers from trade
    records (D102), then most claims, then key, so the gate cap never drops an actionable tender
    in favour of a closed one (D71), nor a proven buyer in favour of a past award."""

    def still_open(c: Candidate) -> bool:
        return c.window_end is not None and c.window_end >= today

    return sorted(
        candidates,
        key=lambda c: (not still_open(c), c.stream != RadarStream.TRADE, -len(c.claims), c.key),
    )


async def run_radar(
    spec: ClientSpec,
    *,
    as_of: datetime,
    http: Any,  # httpx.AsyncClient | None; httpx stays out of radar imports (rule: sensors/)
    fetcher: PageFetcher,
    concepts: list[EventConceptRow],
    run: RunContext,
    settings: Settings | None = None,
    session: Any = None,
    evidence_out: list[tuple[EvidenceDocument, LedgerResult]] | None = None,
    strategy: Any = None,  # radar.strategy.Strategy; Any keeps the database layer out
) -> RadarRun:
    """Run the whole radar pipeline for one client and return the run record (D61).
    `evidence_out`, when given, receives every document read with its ledger result, so the
    caller can save the run (`radar.persist`, D86)."""
    settings = settings or get_settings()
    cap = settings.radar_run_budget_usd
    notes: list[str] = []
    llm_calls = 0

    def over_budget() -> bool:
        return run.spent > cap

    # 1. discover (sensors with queries shifted to the run date, then lead upgrade)
    queries = prepare_queries(spec.sensors, as_of.date(), settings)
    rng = random.Random(f"{spec.id}|{as_of.isoformat()}")  # seeded: a run is reproducible
    query_propensity: dict[str, float] = {}
    if strategy is not None and strategy.labels >= settings.learning_min_labels:
        queries, query_propensity = _strategy_queries(queries, strategy, rng, settings)
        notes.append(
            f"strategy v{strategy.version} chose the searches "
            f"({sum(len(q) for q in queries.values())} run; D89)"
        )
    found = await discover(spec, queries, http=http, fetcher=fetcher, settings=settings)
    notes.extend(found.notes)
    # A page fetched during this run is available at the run's moment, never later: sensors
    # stamp search results with the clock, which on replay would be today (D78).
    found.documents[:] = [
        d.model_copy(update={"available_at": as_of})
        if d.available_at is not None and d.available_at > as_of
        else d
        for d in found.documents
    ]

    # 2. the evidence ledger, per document (no database)
    results: list[tuple[EvidenceDocument, LedgerResult]] = []
    kinds: dict[str, int] = {}
    stopped = False
    for index, doc in enumerate(found.documents):
        if over_budget():
            skipped = len(found.documents) - index
            notes.append(
                f"run budget of ${cap} reached: {skipped} document(s) not read, "
                "and no candidate was gated"
            )
            stopped = True
            break
        try:
            result = await build_evidence(
                doc, concepts, [], run=run, session=session, settings=settings
            )
        except BudgetExceeded as exc:
            notes.append(f"stopped reading documents: {exc}")
            stopped = True
            break
        except _ITEM_FAILURES as exc:
            notes.append(f"document skipped ({type(exc).__name__}): {doc.url}")
            continue
        llm_calls += result.llm_calls
        results.append((doc, result))
        kind = result.eligibility.kind.value
        kinds[kind] = kinds.get(kind, 0) + 1

    # 3. candidates (code only); unidentified subjects are rejected here
    if evidence_out is not None:
        evidence_out.extend(results)
    candidates, rejected = build_candidates(results, settings=settings)
    rejected = list(rejected)
    # The client's current customers are never shown as new (D101). Matched on the name key
    # without country; only a count is noted, since the list is the client's own data.
    if spec.existing_customers:
        known = {company_key(n, None, settings) for n in spec.existing_customers}
        before = len(candidates)
        candidates = [c for c in candidates if company_key(c.name, None, settings) not in known]
        if before > len(candidates):
            notes.append(f"{before - len(candidates)} existing customer(s) left out as not new")

    # 3b. the register check (D103): UK companies looked up before any model call; dissolved
    # companies and the client's non-buyer activities are rejected by code
    candidates, register_rejected, register_notes = await register_check(
        candidates, spec, http=http, as_of=as_of, settings=settings
    )
    rejected.extend(register_rejected)
    notes.extend(register_notes)

    # 4. gate every candidate (best-evidenced first, capped), skeptic only on passed ones
    ordered = _gate_order(candidates, as_of.date())
    limit = settings.radar_max_gate_candidates
    if len(ordered) > limit:
        notes.append(f"{len(ordered) - limit} candidate(s) not gated: cap of {limit} reached")
        ordered = ordered[:limit]
    # Candidates are gated several at a time (radar_gate_concurrency): the calls are independent,
    # and each outcome is kept in its slot so the run record keeps the gate order.
    gate_slots = asyncio.Semaphore(settings.radar_gate_concurrency)
    outcomes: list[tuple[str, Any]] = [("skipped", None)] * len(ordered)
    gate_calls = [0] * len(ordered)

    async def gate_one(i: int, candidate: Candidate) -> None:
        nonlocal stopped
        async with gate_slots:
            if stopped or over_budget():
                if not stopped:
                    notes.append(f"run budget of ${cap} reached: remaining candidates not gated")
                    stopped = True
                outcomes[i] = ("not_gated", None)
                return
            decision: GateDecision | None = None
            try:
                decision = await gate_candidate(
                    candidate, spec, run=run, session=session, settings=settings
                )
                if candidate.claims:
                    gate_calls[i] += 1  # a candidate with no claim is rejected by code, no call
                if not decision.passed:
                    outcomes[i] = ("rejected", RejectedEntry(candidate=candidate, gate=decision))
                    return
                if over_budget():
                    outcomes[i] = ("not_investigated", candidate.name)
                    stopped = True
                    return
                finding = await skeptic(
                    candidate, decision, spec, run=run, session=session, settings=settings
                )
                gate_calls[i] += 1
            except BudgetExceeded as exc:
                if not stopped:
                    notes.append(f"stopped: {exc}")
                stopped = True
                passed_gate = decision is not None and decision.passed
                outcomes[i] = ("not_investigated" if passed_gate else "not_gated", candidate.name)
                return
            except _ITEM_FAILURES as exc:
                notes.append(f"candidate skipped ({type(exc).__name__}): {candidate.name}")
                return
            outcomes[i] = ("passed", (candidate, decision, finding))

    await asyncio.gather(*(gate_one(i, c) for i, c in enumerate(ordered)))
    llm_calls += sum(gate_calls)
    passed: list[tuple[Candidate, GateDecision, SkepticFinding]] = []
    not_gated = 0
    not_investigated: list[str] = []
    for kind, value in outcomes:
        if kind == "passed":
            passed.append(value)
        elif kind == "rejected":
            rejected.append(value)
        elif kind == "not_gated":
            not_gated += 1
        elif kind == "not_investigated":
            not_investigated.append(value)
    if not_gated:
        notes.append(f"{not_gated} candidate(s) not gated: run budget reached")
    if not_investigated:
        notes.append(
            "passed the gate but not briefed (no skeptic review, run budget reached): "
            + ", ".join(not_investigated)
        )

    # 5. rank (code only) and assemble the run record
    entries = rank(
        passed,
        as_of=as_of,
        settings=settings,
        offer=spec.offer,
        terms=spec.offer_terms,
        related_terms=spec.related_terms,
    )

    # A page that tried to steer the system marks every entry it supports (D85).
    if found.steered_urls:
        steered = set(found.steered_urls)
        entries = [
            e.model_copy(update={"steered": True})
            if any(c.url in steered for c in e.candidate.claims)
            else e
            for e in entries
        ]

    # One brief slot goes to a uniformly random lead from below the cut (D89).
    if settings.radar_exploration_slots > 0 and entries:
        _, below = main_selection(
            entries, settings.radar_brief_main_entries - settings.radar_exploration_slots
        )
        pick = exploration_pick(len(below), rng)
        if pick is not None:
            chosen, propensity = below[pick[0]], pick[1]
            entries = [
                e.model_copy(update={"exploration": True, "propensity": propensity})
                if e is chosen
                else e
                for e in entries
            ]

    # 6. likely bidders for open tenders: who won similar awards there recently (D81, code only)
    entries, bidder_notes = await likely_bidders(
        entries,
        as_of=as_of,
        http=http,
        concepts=concepts,
        run=run,
        settings=settings,
        evidence_out=evidence_out,
    )
    notes.extend(bidder_notes)

    # 7. company fit from the account's own website (D96, code only)
    entries, fit_notes = await company_fit(
        entries,
        spec,
        http=http,
        fetcher=fetcher,
        as_of=as_of,
        settings=settings,
        evidence_out=evidence_out,
    )
    notes.extend(fit_notes)

    # 8. the daily edition labels (D103, code only)
    entries = label_entries(entries, as_of.date(), settings)
    return RadarRun(
        client_id=spec.id,
        offer=spec.offer,
        client_name=spec.name,
        as_of=as_of,
        queries=queries,
        documents_by_kind=dict(sorted(kinds.items())),
        leads=found.leads,
        upgraded=found.upgraded,
        entries=entries,
        rejected=rejected,
        llm_calls=llm_calls,
        cost_usd=Decimal(run.spent),
        notes=notes,
        found_by={
            str(doc.id): found.found_by[str(doc.id)]
            for doc, _ in results
            if str(doc.id) in found.found_by
        },
        query_propensity=query_propensity,
    )


def _strategy_queries(
    queries: dict[str, list[Any]], strategy: Any, rng: random.Random, settings: Settings
) -> tuple[dict[str, list[Any]], dict[str, float]]:
    """Per sensor, a Thompson choice of the searches to run (D89): learned beliefs where a
    search has labels, its source's (or the pooled) belief otherwise; every search keeps the
    exploration floor. Returns the chosen searches and each one's selection probability."""
    post = strategy.posteriors()
    chosen: dict[str, list[Any]] = {}
    propensity: dict[str, float] = {}
    for sensor, listed in queries.items():
        by_ref = query_keys_by_ref({sensor: listed})
        keyed = {by_ref[f"{sensor}:{i}"]: q for i, q in enumerate(listed, start=1)}
        fallback = post.yields.get("source", {}).get(sensor, post.pooled)
        beliefs: dict[str, Beta] = {k: post.yields.get("query", {}).get(k, fallback) for k in keyed}
        for paused in strategy.paused:  # paused searches only run on the exploration floor
            if paused in beliefs:
                beliefs[paused] = Beta(1.0, 99.0)
        keep = max(1, math.ceil(settings.learning_query_keep_share * len(keyed)))
        picked, shares = choose_queries(
            beliefs, keep, floor=settings.learning_explore_floor, rng=rng
        )
        chosen[sensor] = [q for k, q in keyed.items() if k in picked]
        for index, k in enumerate(k for k in keyed if k in picked):
            propensity[f"{sensor}:{index + 1}"] = shares[k]
    return chosen, propensity
