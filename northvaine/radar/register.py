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

from datetime import datetime
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from northvaine.core.models import EvidenceKind
from northvaine.core.settings import Settings
from northvaine.radar.models import (
    Candidate,
    CandidateClaim,
    ClientSpec,
    GateDecision,
    RadarStream,
    RegisterFacts,
    RejectedAs,
    RejectedEntry,
)
from northvaine.radar.verify import claim_fingerprint
from northvaine.sensors.base import SensorError, content_hash
from northvaine.sensors.companies_house import (
    CompaniesHouseClient,
    RegisterRecord,
    render_register_text,
    sic_descriptions,
)

__all__ = ["register_check"]

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
        status=record.status,
        incorporated=record.incorporated,
        sic_codes=list(record.sic_codes),
        renamed_on=max(renamed) if renamed else None,
        controlled_by=[c.name for c in record.controllers],
        control_changed_on=record.control_changed_on,
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


async def register_check(
    candidates: list[Candidate],
    spec: ClientSpec,
    *,
    http: Any,
    as_of: datetime,
    settings: Settings,
) -> tuple[list[Candidate], list[RejectedEntry], list[str]]:
    """(candidates kept, rejected by the register, notes). A no-op unless enabled."""
    if not _enabled(spec, settings):
        return candidates, [], []
    client = CompaniesHouseClient(client=http, settings=settings)
    uk = [c for c in candidates if c.country == REGISTER_COUNTRY]
    # Proven buyers from trade records first: the register matters most for them.
    uk.sort(key=lambda c: (c.stream != RadarStream.TRADE, c.key))
    chosen = {c.key for c in uk[: settings.radar_register_max_lookups]}
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
