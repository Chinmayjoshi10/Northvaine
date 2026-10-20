"""Investigate the top leads within the search cap (D117).

The top leads are usually proven by records (imports, register, own site) but have no dated
reason to call now. A short, budgeted look at the top few can find one: an expansion, a new site,
a contract, a new range. Each lead gets at most two web searches (the second only when the first
results never name the company), a few documents are read, and everything goes through the
ordinary evidence ledger: claims and events are extracted and quote-verified exactly as everywhere
else. Only verified facts about this company are attached; text aimed at AI systems is removed
before any model sees it (rules #2, #7, #10).
"""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlsplit

from northvaine.brain.budget import RunContext
from northvaine.brain.errors import (
    BudgetExceeded,
    LlmInvalidOutput,
    LlmTimeout,
    LlmTransportError,
)
from northvaine.core.models import (
    EventConceptRow,
    EvidenceDocument,
    EvidenceKind,
    LedgerResult,
)
from northvaine.core.settings import ConfigError, Settings, get_settings
from northvaine.radar.brief import rank
from northvaine.radar.discover import (
    PageFetcher,
    neutralise_steering,
    strip_contacts,
    upgraded_document,
)
from northvaine.radar.entities import build_candidates, company_key
from northvaine.radar.ledger import build_evidence, evidence_document_from_sensor
from northvaine.radar.models import (
    Candidate,
    ClientSpec,
    RadarStream,
    RankedEntry,
)
from northvaine.radar.verify import is_evidence_document
from northvaine.sensors.base import SensorError, SensorQuery
from northvaine.sensors.fetch import host_denied
from northvaine.sensors.registry import get_sensor

__all__ = ["investigate", "rerank"]

_ITEM_FAILURES = (LlmInvalidOutput, LlmTimeout, LlmTransportError)
_GENERIC_WORDS = "news expansion project"
REASON_PREFIX = "Investigated: "
_STREAM_ORDER = (
    RadarStream.TENDER,
    RadarStream.TRADE,
    RadarStream.ANNOUNCEMENT,
    RadarStream.AWARD,
)


def _fold(text: str) -> str:
    folded = unicodedata.normalize("NFKC", text).casefold()
    return re.sub(r"[\W_]+", " ", folded).strip()


def _name_part(name: str, settings: Settings) -> str:
    """The name without legal forms or punctuation (the matching rule of `company_key`)."""
    return company_key(name, None, settings).partition(":")[2]


def _own_names(candidate: Candidate, settings: Settings) -> set[str]:
    names = [candidate.name, *candidate.aliases]
    if candidate.company_register is not None and candidate.company_register.name:
        names.append(candidate.company_register.name)
    return {part for part in (_name_part(n, settings) for n in names) if part}


def _names_company(text: str, own: set[str]) -> bool:
    haystack = f" {_fold(text)} "
    return any(f" {part} " in haystack for part in own)


def _search_name(candidate: Candidate) -> str:
    register = candidate.company_register
    return (register.name if register and register.name else None) or candidate.name


def _queries(candidate: Candidate, as_of: datetime) -> tuple[SensorQuery, SensorQuery]:
    """(first, rephrased): the quoted name with generic news words, then the quoted name alone."""
    name = f'"{_search_name(candidate)}"'
    today = as_of.date()
    common: dict[str, Any] = {
        "countries": [candidate.country] if candidate.country else [],
        "published_from": today - timedelta(days=365),
        "published_to": today,
        "max_results": 5,
    }
    return (
        SensorQuery(text=f"{name} {_GENERIC_WORDS}", **common),
        SensorQuery(text=name, **common),
    )


def _attach(
    entry: RankedEntry,
    found: list[Candidate],
    own: set[str],
    settings: Settings,
) -> tuple[RankedEntry, int, int]:
    """The entry with the verified claims and events about this company added, refs renumbered
    after the candidate's own. Returns (entry, new claims, documents behind them)."""
    mine = [c for c in found if own & {_name_part(n, settings) for n in (c.name, *c.aliases)}]
    candidate = entry.candidate
    claims = list(candidate.claims)
    by_fp = {k.fingerprint: k.ref for k in claims}
    events = list(candidate.events)
    seen_events = {e.fingerprint for e in events}
    added_docs: set[Any] = set()
    added = 0
    added_events = 0
    for other in mine:
        remap: dict[str, str] = {}
        for k in other.claims:
            ref = by_fp.get(k.fingerprint)
            if ref is None:
                ref = f"C{len(claims) + 1}"
                claims.append(k.model_copy(update={"ref": ref}))
                by_fp[k.fingerprint] = ref
                added += 1
                added_docs.add(k.document_id)
            remap[k.ref] = ref
        for e in other.events:
            if e.fingerprint in seen_events:
                continue
            seen_events.add(e.fingerprint)
            refs = list(dict.fromkeys(remap.get(r, r) for r in e.claim_refs))
            events.append(e.model_copy(update={"claim_refs": refs}))
            added_events += 1
    if not added and not added_events:
        return entry, 0, 0
    streams = {*candidate.streams, *(s for o in mine for s in o.streams)}
    new_candidate = candidate.model_copy(
        update={
            "claims": claims,
            "events": events,
            "streams": [s for s in _STREAM_ORDER if s in streams],
        }
    )
    reasons = list(entry.rank_reasons)
    if added:
        reasons.append(f"{REASON_PREFIX}{added} new fact(s) from {len(added_docs)} source(s)")
    return (
        entry.model_copy(update={"candidate": new_candidate, "rank_reasons": reasons}),
        added,
        len(added_docs),
    )


async def _documents_for(
    candidate: Candidate,
    sensor: Any,
    searches_left: int,
    *,
    as_of: datetime,
    fetcher: PageFetcher,
    settings: Settings,
    notes: list[str],
) -> tuple[list[EvidenceDocument], int, list[str]]:
    """(documents, searches used, urls whose steering text was removed) for one lead."""
    own = _own_names(candidate, settings)
    first, again = _queries(candidate, as_of)
    used = 0
    results: list[Any] = []
    for query in (first, again):
        if used >= 2 or used >= searches_left:
            break
        used += 1
        try:
            found = await sensor.search(query)
        except (SensorError, ConfigError) as exc:
            notes.append(f"investigation search failed for {candidate.name}: {exc}")
            break
        results = list(found.documents)
        if any(_names_company(f"{d.title or ''} {d.text}", own) for d in results):
            break  # the rephrase happens only when no result names the company
    documents: list[EvidenceDocument] = []
    steered: list[str] = []
    for sdoc in results[: settings.radar_investigate_max_docs]:
        host = urlsplit(sdoc.url).hostname or ""
        if host_denied(host, settings.fetch_deny_hosts):
            continue
        doc = evidence_document_from_sensor(sdoc)
        if is_evidence_document(doc, settings).kind == EvidenceKind.LEAD:
            page = await fetcher.fetch(sdoc.url)
            upgraded = upgraded_document(page, doc)
            if upgraded is None:
                continue
            doc = upgraded
        elif doc.text:
            doc = doc.model_copy(update={"text": strip_contacts(doc.text)})
        if doc.available_at is not None and doc.available_at > as_of:
            doc = doc.model_copy(update={"available_at": as_of})
        if doc.text:
            clean, removed = neutralise_steering(doc.text, settings)
            if removed:
                steered.append(doc.url)
                doc = doc.model_copy(update={"text": clean})
        documents.append(doc)
    return documents, used, steered


async def investigate(
    entries: list[RankedEntry],
    spec: ClientSpec,
    *,
    http: Any,
    fetcher: PageFetcher,
    concepts: list[EventConceptRow],
    run: RunContext,
    session: Any = None,
    as_of: datetime,
    settings: Settings | None = None,
    evidence_out: list[tuple[EvidenceDocument, LedgerResult]] | None = None,
) -> tuple[list[RankedEntry], list[str]]:
    """The top entries with any new verified facts attached; notes with counts only.

    At most `radar_investigate_top` leads, two searches each, `radar_investigate_max_searches`
    for the run, `radar_investigate_max_docs` documents per lead. Stops when the run budget is
    spent. A failed search or document is a note, never a failed run."""
    cfg = settings or get_settings()
    notes: list[str] = []
    if cfg.radar_investigate_top <= 0 or cfg.radar_investigate_max_searches <= 0 or not entries:
        return entries, notes
    try:
        sensor = get_sensor("tavily", client=http, settings=cfg)
    except Exception as exc:
        return entries, [f"investigation skipped: {exc}"]
    cap = cfg.radar_run_budget_usd
    searches = 0
    new_facts = 0
    investigated = 0
    updated: dict[int, RankedEntry] = {}
    for entry in sorted(entries, key=lambda e: e.rank)[: cfg.radar_investigate_top]:
        if searches >= cfg.radar_investigate_max_searches:
            break
        if run.spent > cap:
            notes.append(f"investigation stopped: run budget of ${cap} reached")
            break
        investigated += 1
        candidate = entry.candidate
        docs, used, steered = await _documents_for(
            candidate,
            sensor,
            cfg.radar_investigate_max_searches - searches,
            as_of=as_of,
            fetcher=fetcher,
            settings=cfg,
            notes=notes,
        )
        searches += used
        results: list[tuple[EvidenceDocument, LedgerResult]] = []
        for doc in docs:
            if run.spent > cap:
                notes.append(f"investigation stopped: run budget of ${cap} reached")
                break
            try:
                ledger = await build_evidence(
                    doc, concepts, [], run=run, session=session, settings=cfg
                )
            except BudgetExceeded as exc:
                notes.append(f"investigation stopped: {exc}")
                break
            except _ITEM_FAILURES as exc:
                notes.append(f"investigation document skipped ({type(exc).__name__}): {doc.url}")
                continue
            results.append((doc, ledger))
        if evidence_out is not None:
            evidence_out.extend(results)
        found, _ = build_candidates(results, settings=cfg)
        attached, added, _ = _attach(entry, found, _own_names(candidate, cfg), cfg)
        if attached is not entry:
            if steered and any(k.url in set(steered) for k in attached.candidate.claims):
                attached = attached.model_copy(update={"steered": True})
            updated[id(entry)] = attached
        new_facts += added
    notes.append(
        f"investigated {investigated} lead(s): {searches} search(es), {new_facts} new fact(s)"
    )
    return [updated.get(id(e), e) for e in entries], notes


def rerank(
    entries: list[RankedEntry], spec: ClientSpec, *, as_of: datetime, settings: Settings
) -> list[RankedEntry]:
    """Put the entries in ranking order again after new facts were added: the same `rank` rule
    on the changed candidates, keeping everything else an entry has (fit, bidders, flags). Only
    the rank-derived fields are taken from the fresh ranking."""
    fresh = rank(
        [(e.candidate, e.gate, e.skeptic) for e in entries],
        as_of=as_of,
        settings=settings,
        offer=spec.offer,
        terms=spec.offer_terms,
        related_terms=spec.related_terms,
    )
    by_candidate = {id(f.candidate): f for f in fresh}
    out: list[RankedEntry] = []
    for e in entries:
        f = by_candidate[id(e.candidate)]
        level = f.evidence_level
        if level in ("generic_mention", "no_evidence") and e.fit_level == "stated":
            level = "company_fit"  # fit.py's upgrade, kept (D96)
        reasons = list(f.rank_reasons) + [r for r in e.rank_reasons if r.startswith(REASON_PREFIX)]
        out.append(
            e.model_copy(
                update={
                    "rank": f.rank,
                    "rank_reasons": reasons,
                    "requirement": f.requirement,
                    "requirement_ref": f.requirement_ref,
                    "contract_nature": f.contract_nature,
                    "nature_derived": f.nature_derived,
                    "account_role": f.account_role,
                    "evidence_level": level,
                }
            )
        )
    return sorted(out, key=lambda e: e.rank)
