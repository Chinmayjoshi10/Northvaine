"""Radar shapes (M5, D57-D66): the client spec, candidates, gate and skeptic verdicts, ranked
entries and the run record. Radar-only, so `core/models.py` stays untouched.

Pure data: no network, no database, no environment read at import.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

from pydantic import Field, model_validator

from northvaine.core.models import EvidenceDocument, EvidenceKind, Iso2, NorthvaineModel
from northvaine.core.settings import get_settings
from northvaine.sensors.base import SensorQuery

__all__ = [
    "AgainstPoint",
    "Candidate",
    "CandidateClaim",
    "CandidateEvent",
    "ClientSpec",
    "DiscoverResult",
    "GateDecision",
    "RadarRun",
    "RadarStream",
    "RankedEntry",
    "RegisterFacts",
    "RejectedAs",
    "RejectedEntry",
    "SkepticFinding",
    "UpgradedPage",
    "load_client_spec",
    "stream_is_enumerable",
]

REPO_ROOT = Path(__file__).resolve().parents[2]


class RadarStream(StrEnum):
    """Which kind of signal an entry is (D60)."""

    TENDER = "tender"
    AWARD = "award"
    ANNOUNCEMENT = "announcement"
    TRADE = "trade"  # official trade records: a proven buyer of the client's product codes (D102)


def stream_is_enumerable(stream: RadarStream | str) -> bool:
    """Tenders, awards and trade records are listed in official registers; announcements are
    not (D30, D102)."""
    return RadarStream(stream) in {RadarStream.TENDER, RadarStream.AWARD, RadarStream.TRADE}


class RejectedAs(StrEnum):
    UNIDENTIFIED = "unidentified"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    COMPETITOR = "competitor"
    RESELLER = "reseller"
    PUBLISHER = "publisher"
    NOT_A_BUYER = "not_a_buyer"
    NOT_AN_ORGANISATION = "not_an_organisation"


class ClientSpec(NorthvaineModel):
    id: str
    offer: str
    # The client's company name as they gave it (onboarding); shown in the app header.
    name: str | None = None
    markets: list[Iso2]
    sensors: dict[str, list[SensorQuery]]
    # What the client sells, as words a source would use, in any language (D82). Data, set at
    # onboarding. Empty means the terms are derived from `offer` (weaker: English only).
    offer_terms: list[str] = Field(default_factory=list)
    # Words for related products: a quote naming one is "related", a possibility that needs a
    # specification check, never "stated" (D84).
    related_terms: list[str] = Field(default_factory=list)
    # The buyer model (D101): who buys from this client, as data. Empty means "as before": the
    # gate treats traders of the offer as resellers. A client whose customers are importers or
    # distributors lists those roles here, and the gate then counts them as buyers.
    buyer_roles: list[str] = Field(default_factory=list)
    # Who is competition rather than a buyer, in plain words (e.g. "other manufacturers of the
    # same products").
    not_buyers: list[str] = Field(default_factory=list)
    # Official codes buyers use for the offer, scheme-prefixed: "hs:<6-8 digits>", "cpv:<8>".
    product_codes: list[str] = Field(default_factory=list)
    # The client's current customers: never shown as new, used as routes. Real lists live only
    # in specs outside the repo.
    existing_customers: list[str] = Field(default_factory=list)
    # Registered activities that are never buyers for this client (D103), scheme-prefixed, e.g.
    # "sic:49410". Data per client: a code that is never a buyer for one client can be the very
    # customer of another.
    not_buyer_codes: list[str] = Field(default_factory=list)


def load_client_spec(client_id: str, clients_dir: Path | None = None) -> ClientSpec:
    """Read `<clients_dir>/<client_id>.json`; the default is `settings.radar_clients_dir`."""
    if clients_dir is None:
        configured = Path(get_settings().radar_clients_dir)
        clients_dir = configured if configured.is_absolute() else REPO_ROOT / configured
    path = clients_dir / f"{client_id}.json"
    if not path.is_file():
        raise FileNotFoundError(f"client spec {client_id!r} not found at {path}")
    return ClientSpec.model_validate(json.loads(path.read_text(encoding="utf-8")))


class CandidateClaim(NorthvaineModel):
    ref: str  # "C1", "C2", ...
    fingerprint: str
    document_id: UUID
    statement: str
    source_quote: str
    source_name: str
    url: str
    available_at: datetime | None
    evidence_kind: EvidenceKind
    verified_by: str
    upgraded_from: str | None


class CandidateEvent(NorthvaineModel):
    event_type: str
    description: str
    occurred_on: date | None
    available_at: datetime | None
    claim_refs: list[str]
    slots: dict[str, Any]
    fingerprint: str


class RegisterFacts(NorthvaineModel):
    """Company-level facts from a business register (D103), for labels and the brief. Each one
    is also a verified claim on the candidate."""

    number: str
    status: str
    incorporated: date | None = None
    sic_codes: list[str] = Field(default_factory=list)
    renamed_on: date | None = None
    controlled_by: list[str] = Field(default_factory=list)  # companies only
    control_changed_on: date | None = None


class Candidate(NorthvaineModel):
    key: str
    name: str
    country: Iso2 | None
    aliases: list[str]
    roles: list[str]
    stream: RadarStream
    streams: list[RadarStream]
    events: list[CandidateEvent]
    claims: list[CandidateClaim]
    window_start: date | None
    window_end: date | None
    window_estimated: bool
    window_note: str
    company_register: RegisterFacts | None = None
    # D109: short reasons it looks like the client's customers (never an existing customer's name)
    like_customers: list[str] = Field(default_factory=list)


class GateDecision(NorthvaineModel):
    passed: bool
    rejected_as: RejectedAs | None
    by: Literal["code", "llm"]
    reason: str
    direct_buyer: bool | None
    buyer_reason: str | None
    demand_reason: str | None
    suggested_action: str | None
    cited_refs: list[str]

    @model_validator(mode="after")
    def _passed_iff_not_rejected(self) -> GateDecision:
        if self.passed != (self.rejected_as is None):
            raise ValueError("passed must be true exactly when rejected_as is None")
        return self


class AgainstPoint(NorthvaineModel):
    claim_ref: str
    why: str


class SkepticFinding(NorthvaineModel):
    stance: Literal["against", "unknown"]
    against: list[AgainstPoint]
    open_questions: list[str]

    @model_validator(mode="after")
    def _against_iff_points(self) -> SkepticFinding:
        if (self.stance == "against") != bool(self.against):
            raise ValueError("stance is 'against' exactly when there are against points")
        return self


class LikelyBidder(NorthvaineModel):
    """A company that won similar awards in the same country recently (D81). Every field comes
    from an official award record, verified by code; nothing is inferred by a model."""

    name: str
    country: str | None
    wins: int = Field(ge=1)
    last_won: date | None
    source_url: str
    quote: str


class FitEvidence(NorthvaineModel):
    """A sentence on the company's own site naming what the client sells (D96): a fit, not a
    purchase."""

    url: str
    quote: str
    term: str
    level: Literal["stated", "related"]
    fingerprint: str


class CompanyContact(NorthvaineModel):
    """The company's own role address and phone, verbatim from its own site (D108). Company
    only: never a person."""

    email: str | None = None
    phone: str | None = None
    url: str


class RankedEntry(NorthvaineModel):
    rank: int = Field(ge=1)
    candidate: Candidate
    gate: GateDecision
    skeptic: SkepticFinding
    strength: Literal["strong", "medium", "weak"]
    rank_reasons: list[str]
    # M5.1 (D80): "stated" when a verified quote names a term of the client's offer, found by
    # code; "inferred" otherwise. Defaults keep run records written before M5.1 readable.
    requirement: Literal["stated", "related", "inferred"] = "inferred"
    requirement_ref: str | None = None
    likely_bidders: list[LikelyBidder] = Field(default_factory=list)  # tenders only (D81)
    # A source page of this entry tried to steer the system; that text was removed (D85).
    steered: bool = False
    # Learning v0 (D89): one brief slot is a uniformly random pick from below the cut, so
    # labels about what the cut throws away stay unbiased; `propensity` is its chance.
    exploration: bool = False
    propensity: float = Field(default=1.0, gt=0, le=1)
    # D94: who the account is and how strong its buying evidence is (radar/account.py). None in
    # run records written before D94; the brief then falls back to `requirement`.
    contract_nature: str | None = None
    nature_derived: bool = False
    account_role: str | None = None
    evidence_level: str | None = None
    # D96: the company's own site, and the sentences on it naming what the client sells.
    company_site: str | None = None
    company_fit: list[FitEvidence] = Field(default_factory=list)
    fit_level: Literal["stated", "related"] | None = None
    company_contact: CompanyContact | None = None  # D108
    # The daily edition (D103): act now / just changed / account to work, and why.
    label: Literal["act_now", "just_changed", "account_to_work"] | None = None
    label_reason: str | None = None
    label_strength: int = 0  # how many dated changes back a just_changed label


class RejectedEntry(NorthvaineModel):
    candidate: Candidate
    gate: GateDecision


class UpgradedPage(NorthvaineModel):
    lead_url: str
    final_url: str | None
    status: int | None
    fetched_at: datetime | None
    title: str | None
    text: str | None
    refused: str | None  # robots | denied | http_<n> | content_type | error
    # The page text before contacts were stripped, kept in memory for the company-contact check
    # only (D108). Excluded from every dump, so recordings and reports never store contacts.
    contact_text: str | None = Field(default=None, exclude=True)


class DiscoverResult(NorthvaineModel):
    documents: list[EvidenceDocument]
    leads: int
    upgraded: list[UpgradedPage]
    notes: list[str]
    steered_urls: list[str] = Field(default_factory=list)  # pages with steering text removed
    # document id -> the queries that found it, as "sensor:index" (1-based, D87)
    found_by: dict[str, list[str]] = Field(default_factory=dict)


class RadarRun(NorthvaineModel):
    client_id: str
    offer: str
    client_name: str | None = None
    as_of: datetime
    queries: dict[str, list[SensorQuery]]
    documents_by_kind: dict[str, int]
    leads: int
    upgraded: list[UpgradedPage]
    entries: list[RankedEntry]
    rejected: list[RejectedEntry]
    llm_calls: int
    cost_usd: Decimal
    notes: list[str]
    # document id -> the queries that found it, as "sensor:index" (1-based, D87); read
    # documents only. Empty in run records written before D87.
    found_by: dict[str, list[str]] = Field(default_factory=dict)
    # query ref ("sensor:index" in `queries`) -> the chance a learned strategy chose it (D89);
    # empty when no strategy chose the searches (every search ran, propensity 1).
    query_propensity: dict[str, float] = Field(default_factory=dict)
