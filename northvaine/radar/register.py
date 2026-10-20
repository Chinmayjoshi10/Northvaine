"""The register check (step 1b, D103): UK candidates looked up at Companies House before the gate.

For each looked-up company:
- its register lines (status, incorporation, activity codes with descriptions, previous names,
  controlling companies) become verified claims on the candidate, so the gate and the brief see
  them. The quotes are the rendered lines, so the code quote check holds by construction.
- code rejects it before any model call when the register shows it is not trading (status other
  than active) or its activity code is one the client lists in `not_buyer_codes`.
- `Candidate.company_register` keeps the facts the daily-edition labels read (new company, rename,
  change of control).

Runs only when the client has a buyer model (`buyer_roles`) and a Companies House key is set, so
clients without one replay exactly as before. Company-level only (see sensors/companies_house).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from northvaine.core.models import EvidenceKind
from northvaine.core.settings import Settings
from northvaine.radar.entities import _PRIMARY_ORDER
from northvaine.radar.models import (
    Candidate,
    CandidateClaim,
    CandidateEvent,
    ClientSpec,
    GateDecision,
    RadarStream,
    RegisterFacts,
    RejectedAs,
    RejectedEntry,
)
from northvaine.radar.timing import timing_signals
from northvaine.radar.verify import claim_fingerprint
from northvaine.sensors.base import SensorError, content_hash
from northvaine.sensors.companies_house import (
    CompaniesHouseClient,
    RegisterRecord,
    render_register_text,
    sic_descriptions,
)

__all__ = [
    "SeedProfile",
    "mark_likeness",
    "mark_timing",
    "merge_by_register",
    "note_import_profile",
    "product_families",
    "register_check",
    "seed_register_profiles",
]

SOURCE = "companies_house"
REGISTER_COUNTRY = "GB"


def _enabled(spec: ClientSpec, settings: Settings) -> bool:
    key = settings.companies_house_api_key
    return bool(spec.buyer_roles) and key is not None and bool(key.get_secret_value())


def _statement(line: str) -> str:
    label, _, value = line.partition(": ")
    return f"The company register states {label.lower()}: {value}" if value else line


def _facts(record: RegisterRecord) -> RegisterFacts:
    renamed = [until for _, until in record.previous_names if until is not None]
    return RegisterFacts(
        number=record.number,
        name=record.name,
        status=record.status,
        incorporated=record.incorporated,
        sic_codes=list(record.sic_codes),
        renamed_on=max(renamed) if renamed else None,
        controlled_by=[c.name for c in record.controllers],
        control_changed_on=record.control_changed_on,
        charge_created_on=record.charge_created_on,
        office_moved_on=record.office_moved_on,
    )


def _with_register(candidate: Candidate, record: RegisterRecord, as_of: datetime) -> Candidate:
    text = render_register_text(record)
    doc_id = uuid5(NAMESPACE_URL, f"{SOURCE}:{content_hash(text)}")
    claims = list(candidate.claims)
    for line in text.split("\n"):
        statement = _statement(line)
        claims.append(
            CandidateClaim(
                ref=f"C{len(claims) + 1}",
                fingerprint=claim_fingerprint(doc_id, statement, line),
                document_id=doc_id,
                statement=statement,
                source_quote=line,
                source_name=SOURCE,
                url=record.url,
                available_at=as_of,
                evidence_kind=EvidenceKind.STRUCTURED,
                verified_by="code",
                upgraded_from=None,
            )
        )
    return candidate.model_copy(update={"claims": claims, "company_register": _facts(record)})


def _refs_starting(candidate: Candidate, prefix: str) -> list[str]:
    return [
        k.ref
        for k in candidate.claims
        if k.source_name == SOURCE and k.source_quote.startswith(prefix)
    ]


def _code_rejection(candidate: Candidate, spec: ClientSpec) -> GateDecision | None:
    facts = candidate.company_register
    if facts is None:
        return None
    if facts.status != "active":
        return GateDecision(
            passed=False,
            rejected_as=RejectedAs.NOT_A_BUYER,
            by="code",
            reason=f"The company register lists its status as {facts.status}: it is not trading.",
            direct_buyer=None,
            buyer_reason=None,
            demand_reason=None,
            suggested_action=None,
            cited_refs=_refs_starting(candidate, "Status: "),
        )
    blocked = [c for c in facts.sic_codes if f"sic:{c}" in set(spec.not_buyer_codes)]
    # Only when every registered activity is a non-buyer one: a company that also wholesales
    # the client's goods stays for the gate to judge.
    if blocked and len(blocked) == len(facts.sic_codes):
        names = sic_descriptions()
        what = "; ".join(f"{c} ({names.get(c, 'unknown activity')})" for c in blocked)
        return GateDecision(
            passed=False,
            rejected_as=RejectedAs.NOT_A_BUYER,
            by="code",
            reason=f"Its registered activity is {what}, which this client lists as not a buyer.",
            direct_buyer=None,
            buyer_reason=None,
            demand_reason=None,
            suggested_action=None,
            cited_refs=_refs_starting(candidate, "Activity (SIC "),
        )
    return None


def mark_timing(
    candidates: list[Candidate], as_of: datetime, settings: Settings
) -> list[Candidate]:
    """Set `timing_signals` (D111). Off when `radar_timing_max_lookups` is 0, so older recordings
    replay with no signals."""
    if settings.radar_timing_max_lookups <= 0:
        return candidates
    days = settings.radar_timing_days
    out: list[Candidate] = []
    for c in candidates:
        signals = timing_signals(c, as_of.date(), days)
        out.append(c.model_copy(update={"timing_signals": signals}) if signals else c)
    return out


async def register_check(
    candidates: list[Candidate],
    spec: ClientSpec,
    *,
    http: Any,
    as_of: datetime,
    settings: Settings,
) -> tuple[list[Candidate], list[RejectedEntry], list[str]]:
    """(candidates kept, rejected by the register, notes). Register lookups run only when
    enabled; timing signals (D111) are then marked on what is kept."""
    kept, rejected, notes = await _register_lookups(
        candidates, spec, http=http, as_of=as_of, settings=settings
    )
    if settings.radar_link_by_register:
        kept, absorbed = merge_by_register(kept)
        if absorbed:
            notes.append(f"linked {absorbed} companies across sources by registration number")
    return mark_timing(kept, as_of, settings), rejected, notes


def _renumbered(
    merged: list[CandidateClaim], group: list[Candidate]
) -> tuple[list[CandidateClaim], list[CandidateEvent]]:
    """The primary's claims then the others', refs continuing (C1..) and event refs remapped. A
    claim already present (same fingerprint, e.g. the shared register lines) is not repeated."""
    by_fp = {k.fingerprint: k.ref for k in merged}
    events = list(group[0].events)
    seen_events = {e.fingerprint for e in events}
    for other in group[1:]:
        remap: dict[str, str] = {}
        for k in other.claims:
            existing = by_fp.get(k.fingerprint)
            if existing is None:
                existing = f"C{len(merged) + 1}"
                merged.append(k.model_copy(update={"ref": existing}))
                by_fp[k.fingerprint] = existing
            remap[k.ref] = existing
        for e in other.events:
            if e.fingerprint in seen_events:
                continue
            seen_events.add(e.fingerprint)
            refs = [remap.get(r, r) for r in e.claim_refs]
            events.append(e.model_copy(update={"claim_refs": list(dict.fromkeys(refs))}))
    return merged, events


def _union(*lists: list[str]) -> list[str]:
    return list(dict.fromkeys(x for items in lists for x in items))


def _merge_group(group: list[Candidate]) -> Candidate:
    trade = [c for c in group if c.stream == RadarStream.TRADE]
    primary = trade[0] if trade else max(group, key=lambda c: len(c.claims))
    ordered = [primary] + [c for c in group if c is not primary]
    claims, events = _renumbered(list(primary.claims), ordered)
    starts = [c.window_start for c in ordered if c.window_start is not None]
    ends = [c.window_end for c in ordered if c.window_end is not None]
    streams = {s for c in ordered for s in c.streams}
    return primary.model_copy(
        update={
            "aliases": _union(primary.aliases, *([c.name, *c.aliases] for c in ordered[1:])),
            "claims": claims,
            "events": events,
            "streams": [s for s in _PRIMARY_ORDER if s in streams],
            "window_start": min(starts) if starts else None,
            "window_end": max(ends) if ends else None,
            "like_customers": _union(*(c.like_customers for c in ordered)),
            "timing_signals": _union(*(c.timing_signals for c in ordered)),
        }
    )


def merge_by_register(candidates: list[Candidate]) -> tuple[list[Candidate], int]:
    """D115: candidates with the same registration number are one company. (candidates, how many
    were merged into another). The merged one takes the first member's place; every claim keeps
    its own document and verified quote. Code only."""
    groups: dict[str, list[Candidate]] = {}
    for c in candidates:
        if c.company_register is not None and c.company_register.number:
            groups.setdefault(c.company_register.number, []).append(c)
    merged_for: dict[int, Candidate | None] = {}
    absorbed = 0
    for group in groups.values():
        if len(group) < 2:
            continue
        merged = _merge_group(group)
        merged_for[id(group[0])] = merged
        for c in group[1:]:
            merged_for[id(c)] = None
        absorbed += len(group) - 1
    if not absorbed:
        return candidates, 0
    out = [merged_for.get(id(c), c) for c in candidates]
    return [c for c in out if c is not None], absorbed


async def _register_lookups(
    candidates: list[Candidate],
    spec: ClientSpec,
    *,
    http: Any,
    as_of: datetime,
    settings: Settings,
) -> tuple[list[Candidate], list[RejectedEntry], list[str]]:
    if not _enabled(spec, settings):
        return candidates, [], []
    client = CompaniesHouseClient(client=http, settings=settings)
    uk = [c for c in candidates if c.country == REGISTER_COUNTRY]
    if settings.radar_link_by_register:
        # D115: awards, tenders and announcements are few and are looked up first, so a trade
        # list cannot use up the cap before a contract winner is reached.
        uk.sort(key=lambda c: (c.stream == RadarStream.TRADE, c.key))
    else:
        # Proven buyers from trade records first: the register matters most for them.
        uk.sort(key=lambda c: (c.stream != RadarStream.TRADE, c.key))
    chosen = {c.key for c in uk[: settings.radar_register_max_lookups]}
    timed = {c.key for c in uk[: settings.radar_timing_max_lookups]}  # D111, same order
    kept: list[Candidate] = []
    rejected: list[RejectedEntry] = []
    found = missing = 0
    notes: list[str] = []
    for candidate in candidates:
        if candidate.key not in chosen:
            kept.append(candidate)
            continue
        try:
            record = await client.lookup(candidate.name)
        except SensorError as exc:
            notes.append(f"register check: lookup failed for {candidate.name}: {exc}")
            kept.append(candidate)
            continue
        if record is None:
            missing += 1
            kept.append(candidate)
            continue
        found += 1
        if candidate.key in timed:
            record, timing_notes = await client.timing(record)
            notes.extend(f"register check: {n}" for n in timing_notes)
        checked = _with_register(candidate, record, as_of)
        decision = _code_rejection(checked, spec)
        if decision is not None:
            rejected.append(RejectedEntry(candidate=checked, gate=decision))
        else:
            kept.append(checked)
    notes.append(
        f"register check: {found} UK companies found at Companies House, {missing} not matched "
        f"by exact name, {len(rejected)} rejected by the register"
    )
    return kept, rejected, notes


# --- customers like yours (D109): code only, no model call, no paid search ----------------------


@dataclass
class SeedProfile:
    """What the client's customers (and leads it approved) look like, from free sources.
    `private` seeds are the client's own customer list: their names are never shown."""

    name: str
    key: str
    private: bool
    families: set[str] = field(default_factory=set)
    sics: set[str] = field(default_factory=set)


def product_families(codes: str) -> set[str]:
    """Product families from an import record's code list: a numeric code keeps its scheme and
    first four digits (e.g. "hs:6907", or "6907" when bare); anything else is kept whole."""
    out: set[str] = set()
    for raw in str(codes or "").split(","):
        code = raw.strip().casefold()
        if not code:
            continue
        scheme, sep, value = code.rpartition(":")
        if value.isdigit():
            out.add(f"{scheme}{sep}{value[:4]}")
        else:
            out.add(code)
    return out


def note_import_profile(
    profiles: dict[str, SeedProfile], candidates: list[Candidate], key_of: Any
) -> None:
    """Add the import families of every seed that appears among this run's trade candidates.
    Call before existing customers are filtered out."""
    from northvaine.radar.brief import _trade_slots  # late: brief imports the radar models

    for c in candidates:
        profile = profiles.get(key_of(c.name))
        if profile is not None and c.stream == RadarStream.TRADE:
            profile.families |= product_families(str(_trade_slots(c).get("codes") or ""))


async def seed_register_profiles(
    profiles: dict[str, SeedProfile],
    candidates: list[Candidate],
    spec: ClientSpec,
    *,
    http: Any,
    key_of: Any,
    settings: Settings,
) -> list[str]:
    """Look seeds up at Companies House (at most `radar_seed_max_lookups`) and keep their
    activity codes. A seed whose import record names another country is skipped. Notes only
    carry counts: a failed lookup is never an error."""
    limit = settings.radar_seed_max_lookups
    if limit <= 0 or not profiles or not _enabled(spec, settings):
        return []
    elsewhere = {key_of(c.name) for c in candidates if c.country not in (None, REGISTER_COUNTRY)}
    chosen = [p for k, p in profiles.items() if k not in elsewhere][:limit]
    client = CompaniesHouseClient(client=http, settings=settings)
    found = failed = 0
    for profile in chosen:
        try:
            record = await client.lookup(profile.name)
        except SensorError:
            failed += 1
            continue
        if record is not None:
            found += 1
            profile.sics |= {str(c) for c in record.sic_codes}
    note = f"customers like yours: {found} of {len(chosen)} seed(s) found at Companies House"
    return [note + (f", {failed} lookup(s) failed" if failed else "")]


def mark_likeness(
    candidates: list[Candidate], profiles: dict[str, SeedProfile], key_of: Any
) -> list[Candidate]:
    """Set `like_customers` on each candidate that shares a registered activity or imported
    product families with a seed. A candidate is never compared with itself."""
    seeds = list(profiles.values())
    if not any(p.sics or p.families for p in seeds):
        return candidates
    from northvaine.radar.brief import _trade_slots  # late: brief imports the radar models

    out: list[Candidate] = []
    for c in candidates:
        own = key_of(c.name)
        sics = set(c.company_register.sic_codes) if c.company_register else set()
        families = product_families(str(_trade_slots(c).get("codes") or ""))
        reasons: list[str] = []
        for p in seeds:
            if p.key == own:
                continue
            who = "one of your customers" if p.private else f"{p.name}, a lead you approved"
            shared = sorted(sics & p.sics)
            if shared:
                reasons.append(f"Same registered business activity (SIC {shared[0]}) as {who}")
            if families & p.families:
                reasons.append(f"Imports the same product families as {who}")
        reasons = list(dict.fromkeys(reasons))[:3]
        out.append(c.model_copy(update={"like_customers": reasons}) if reasons else c)
    return out
