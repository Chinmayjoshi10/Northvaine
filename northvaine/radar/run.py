"""One radar run per client (T5.6): discover, extract, identify, gate, skeptic, rank.

The order is fixed here, in one function (rules #3 and #4): discover -> evidence ledger ->
candidates -> gate -> skeptic (passed candidates only, after their gate) -> rank. Nothing in this
module knows about a client or an industry: everything comes from the `ClientSpec` and settings.
"""

from __future__ import annotations

import importlib.util
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from northvaine.brain.budget import RunContext
from northvaine.brain.errors import BudgetExceeded
from northvaine.core.models import (
    ConceptStatus,
    EventConceptRow,
    EvidenceDocument,
    LedgerResult,
)
from northvaine.core.settings import Settings, get_settings
from northvaine.radar.brief import rank
from northvaine.radar.court import skeptic
from northvaine.radar.discover import PageFetcher, discover, shift_queries
from northvaine.radar.entities import build_candidates
from northvaine.radar.gate import gate_candidate
from northvaine.radar.ledger import build_evidence
from northvaine.radar.models import (
    Candidate,
    ClientSpec,
    GateDecision,
    RadarRun,
    RejectedEntry,
    SkepticFinding,
)

__all__ = ["run_radar", "seeded_concepts"]

MIGRATION_0002 = (
    Path(__file__).resolve().parents[2] / "migrations" / "versions" / "0002_architecture_v2.py"
)
SEED_CREATED_AT = datetime(2026, 1, 1, tzinfo=UTC)


def seeded_concepts() -> list[EventConceptRow]:
    """The level-0 event concepts seeded by migration 0002, in `load_concepts` order
    (level, label). Read from the migration so no label is typed here."""
    spec = importlib.util.spec_from_file_location("nv_migration_0002", MIGRATION_0002)
    if spec is None or spec.loader is None:
        raise FileNotFoundError(f"cannot load {MIGRATION_0002}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
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
        for label, description in sorted(module._SEED)
    ]


def _gate_order(candidates: list[Candidate]) -> list[Candidate]:
    """Most claims first, then key: the gate cap keeps the best-evidenced candidates."""
    return sorted(candidates, key=lambda c: (-len(c.claims), c.key))


async def run_radar(
    spec: ClientSpec,
    *,
    as_of: datetime,
    http: Any,  # httpx.AsyncClient | None; httpx stays out of radar imports (rule: sensors/)
    fetcher: PageFetcher,
    concepts: list[EventConceptRow],
    run: RunContext,
    settings: Settings | None = None,
) -> RadarRun:
    """Run the whole radar pipeline for one client and return the run record (D61)."""
    settings = settings or get_settings()
    cap = settings.radar_run_budget_usd
    notes: list[str] = []
    llm_calls = 0

    def over_budget() -> bool:
        return run.spent > cap

    # 1. discover (sensors with queries shifted to the run date, then lead upgrade)
    queries = shift_queries(spec.sensors, as_of.date())
    found = await discover(spec, queries, http=http, fetcher=fetcher, settings=settings)
    notes.extend(found.notes)

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
            result = await build_evidence(doc, concepts, [], run=run, settings=settings)
        except BudgetExceeded as exc:
            notes.append(f"stopped reading documents: {exc}")
            stopped = True
            break
        llm_calls += result.llm_calls
        results.append((doc, result))
        kind = result.eligibility.kind.value
        kinds[kind] = kinds.get(kind, 0) + 1

    # 3. candidates (code only); unidentified subjects are rejected here
    candidates, rejected = build_candidates(results, settings=settings)
    rejected = list(rejected)

    # 4. gate every candidate (best-evidenced first, capped), skeptic only on passed ones
    ordered = _gate_order(candidates)
    limit = settings.radar_max_gate_candidates
    if len(ordered) > limit:
        notes.append(f"{len(ordered) - limit} candidate(s) not gated: cap of {limit} reached")
        ordered = ordered[:limit]
    passed: list[tuple[Candidate, GateDecision, SkepticFinding]] = []
    not_gated = 0
    not_investigated: list[str] = []
    for candidate in ordered:
        if stopped or over_budget():
            if not stopped:
                notes.append(f"run budget of ${cap} reached: remaining candidates not gated")
                stopped = True
            not_gated += 1
            continue
        decision: GateDecision | None = None
        try:
            decision = await gate_candidate(candidate, spec, run=run, settings=settings)
            if candidate.claims:
                llm_calls += 1  # a candidate with no claim is rejected by code, no call
            if not decision.passed:
                rejected.append(RejectedEntry(candidate=candidate, gate=decision))
                continue
            if over_budget():
                not_investigated.append(candidate.name)
                stopped = True
                continue
            finding = await skeptic(candidate, decision, spec, run=run, settings=settings)
            llm_calls += 1
        except BudgetExceeded as exc:
            notes.append(f"stopped: {exc}")
            stopped = True
            if decision is not None and decision.passed:
                not_investigated.append(candidate.name)
            else:
                not_gated += 1
            continue
        passed.append((candidate, decision, finding))
    if not_gated:
        notes.append(f"{not_gated} candidate(s) not gated: run budget reached")
    if not_investigated:
        notes.append(
            "passed the gate but not briefed (no skeptic review, run budget reached): "
            + ", ".join(not_investigated)
        )

    # 5. rank (code only) and assemble the run record
    entries = rank(passed, as_of=as_of, settings=settings)
    return RadarRun(
        client_id=spec.id,
        offer=spec.offer,
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
    )
