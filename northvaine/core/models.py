"""Shared Pydantic models and enums (T1.0 contract types; T1.6 adds row models below).

The T1.0 types here are frozen for milestone 1.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Any, Generic, Literal, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class NorthvaineModel(BaseModel):
    """Base for every project model: unknown fields are an error."""

    model_config = ConfigDict(extra="forbid")


class JobStatus(StrEnum):
    """Lifecycle of a row in the `jobs` table."""

    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class NewJob(NorthvaineModel):
    """A job to enqueue. Defaults are filled by the queue or the database."""

    kind: str = Field(pattern=r"^[a-z][a-z0-9_]*$", max_length=64)
    payload: dict[str, Any] = Field(default_factory=dict)
    run_after: datetime | None = None  # None = now (DB default)
    max_attempts: int | None = Field(default=None, ge=1)  # None = settings.job_max_attempts
    workspace_id: UUID | None = None


class Job(NorthvaineModel):
    """A `jobs` row exactly as stored in schema v2 (also serves as JobRow)."""

    id: int
    kind: str
    payload: dict[str, Any]
    status: JobStatus
    attempts: int
    max_attempts: int
    run_after: datetime
    locked_at: datetime | None
    locked_by: str | None
    error: str | None
    workspace_id: UUID | None
    created_at: datetime
    finished_at: datetime | None


class EventType(StrEnum):
    """The generic event types of SPEC §1. Never industry-specific."""

    FACILITY_OPENED = "facility_opened"
    """A new site, plant, yard, branch or warehouse opened or announced."""
    CONTRACT_AWARDED = "contract_awarded"
    """A contract or tender award was made to the company."""
    TENDER_PUBLISHED = "tender_published"
    """The company published a tender or request for proposals."""
    HIRING_SURGE = "hiring_surge"
    """A marked rise in open roles at the company."""
    LEADERSHIP_CHANGE = "leadership_change"
    """A senior leader joined, left or changed role."""
    PRODUCT_LAUNCH = "product_launch"
    """The company launched or announced a product or service."""
    MARKET_ENTRY = "market_entry"
    """The company entered a new region or segment."""
    TRADE_MEASURE = "trade_measure"
    """A tariff, quota, duty or other trade rule changed."""
    WEBSITE_CHANGE = "website_change"
    """A material change to the company website."""
    REORDER_DUE = "reorder_due"
    """A past customer is due to reorder based on its history."""
    QUOTE_STALE = "quote_stale"
    """A quote was sent and has had no reply for too long."""
    INBOUND_QUESTION = "inbound_question"
    """A buyer or buyer agent asked a question through the Gateway."""


# ---------------------------------------------------------------------------
# T1.6: enums and row models mirroring schema v2 (schema.sql), in schema order.
# ---------------------------------------------------------------------------

SNAKE = r"^[a-z][a-z0-9_]*$"
Json = dict[str, Any]
JsonDoc = dict[str, Any] | list[Any]


class MembershipRole(StrEnum):
    OWNER = "owner"
    MANAGER = "manager"
    REP = "rep"
    OPS = "ops"


class SourceTier(StrEnum):
    OFFICIAL = "official"
    COMPANY = "company"
    REPORTED = "reported"
    SOCIAL = "social"
    PRIVATE = "private"
    PAID = "paid"


class WorkspaceRelation(StrEnum):
    CUSTOMER = "customer"
    BEST_CUSTOMER = "best_customer"
    PROSPECT = "prospect"
    COMPETITOR = "competitor"
    SUPPRESSED = "suppressed"


class ThesisOrigin(StrEnum):
    GENERATED = "generated"
    USER = "user"
    DISCOVERED = "discovered"


class ThesisStatus(StrEnum):
    ACTIVE = "active"
    EXPLORING = "exploring"
    RETIRED = "retired"


class CaseDirection(StrEnum):
    OUTBOUND = "outbound"
    INBOUND = "inbound"


class CaseStage(StrEnum):
    CANDIDATE = "candidate"
    GATED = "gated"
    INVESTIGATED = "investigated"
    BRIEFED = "briefed"
    APPROVED = "approved"
    CONTACTED = "contacted"
    REPLIED = "replied"
    MEETING = "meeting"
    SAMPLES = "samples"
    QUOTED = "quoted"
    WON = "won"
    LOST = "lost"
    DISMISSED = "dismissed"


class EvidenceStance(StrEnum):
    FOR = "for"
    AGAINST = "against"
    UNKNOWN = "unknown"


class MessageDirection(StrEnum):
    OUT = "out"
    IN = "in"


class Counterpart(StrEnum):
    HUMAN = "human"
    AGENT = "agent"


class MessageStatus(StrEnum):
    DRAFT = "draft"
    APPROVED = "approved"
    SENT = "sent"
    RECEIVED = "received"


class FeedbackRating(StrEnum):
    GOOD = "good"
    NOT_RELEVANT = "not_relevant"
    WRONG_FACTS = "wrong_facts"
    LATER = "later"


class QuestionStatus(StrEnum):
    PENDING = "pending"
    ASKED = "asked"
    ANSWERED = "answered"
    SKIPPED = "skipped"


class Learner(StrEnum):
    WORLD = "world"
    ORG = "org"
    BUYING = "buying"
    RESEARCH = "research"
    ALLOCATOR = "allocator"


class ConceptStatus(StrEnum):
    ACTIVE = "active"
    PROPOSED = "proposed"
    MERGED = "merged"
    RETIRED = "retired"


class HypothesisStatus(StrEnum):
    PROPOSED = "proposed"
    EXPLORING = "exploring"
    EXPLOITING = "exploiting"
    DEGRADED = "degraded"
    RETIRED = "retired"
    REJECTED = "rejected"


class HypothesisOrigin(StrEnum):
    LLM_PRIOR = "llm_prior"
    HISTORY_MINING = "history_mining"
    WORLD_LIFT = "world_lift"
    ERROR_DRIVEN = "error_driven"
    MISSED_OPPORTUNITY = "missed_opportunity"
    CROSS_ORG = "cross_org"
    OWNER = "owner"


class PlaybookStatus(StrEnum):
    ACTIVE = "active"
    EXPLORING = "exploring"
    RETIRED = "retired"


class ProgramStatus(StrEnum):
    ACTIVE = "active"
    TRIAL = "trial"
    PAUSED = "paused"
    RETIRED = "retired"


class ExpectationStatus(StrEnum):
    PENDING = "pending"
    MET = "met"
    MISSED = "missed"


class DecisionKind(StrEnum):
    BRIEF = "brief"
    SEARCH = "search"
    INVESTIGATION = "investigation"
    QUESTION = "question"


class MissedSource(StrEnum):
    INBOUND = "inbound"
    WIN = "win"
    PUBLIC_AWARD = "public_award"


class PostmortemStatus(StrEnum):
    PENDING = "pending"
    NOT_SURFACED = "not_surfaced"
    SURFACED_DROPPED = "surfaced_dropped"
    SURFACED_LATE = "surfaced_late"
    SURFACED_IN_TIME = "surfaced_in_time"


class OpenQuestionStatus(StrEnum):
    OPEN = "open"
    ANSWERED = "answered"
    DROPPED = "dropped"


# ============ TENANCY ============


class WorkspaceRow(NorthvaineModel):
    id: UUID
    name: str
    primary_domain: str | None
    created_at: datetime


class UserRow(NorthvaineModel):
    id: UUID
    email: str
    name: str | None


class MembershipRow(NorthvaineModel):
    workspace_id: UUID
    user_id: UUID
    role: MembershipRole
    territory: JsonDoc | None


# ============ WORLD LAYER ============


class CompanyRow(NorthvaineModel):
    id: UUID
    primary_domain: str | None
    name: str
    aliases: list[str]
    country: str | None = Field(pattern=r"^[A-Z]{2}$")  # ISO 3166-1 alpha-2
    locality: str | None
    industry_codes: list[str]
    attributes: Json
    updated_at: datetime


class SourceRow(NorthvaineModel):
    id: UUID
    name: str
    tier: SourceTier
    trust: float


class DocumentRow(NorthvaineModel):
    id: UUID
    source_id: UUID | None
    url: str
    content_hash: str
    title: str | None
    text: str
    published_on: date | None
    fetched_at: datetime
    workspace_id: UUID | None
    available_at: datetime | None
    external_id: str | None = None
    group_key: str | None = None
    meta: dict[str, Any] = Field(default_factory=dict)


class DocumentChunkRow(NorthvaineModel):
    id: UUID
    document_id: UUID | None
    text: str
    embedding: list[float] | None


class ClaimStatus(StrEnum):
    """Why a claim is or is not verified (migration 0005 CHECK list, D49)."""

    PENDING = "pending"
    VERIFIED = "verified"
    QUOTE_NOT_FOUND = "quote_not_found"
    QUOTE_TOO_SHORT = "quote_too_short"
    UNSUPPORTED = "unsupported"
    INELIGIBLE_DOCUMENT = "ineligible_document"


class ClaimRow(NorthvaineModel):
    id: UUID
    company_id: UUID | None
    document_id: UUID
    statement: str
    source_quote: str
    quote_offset: int | None
    verified: bool
    verified_by: str | None
    extracted_by: str
    created_at: datetime
    status: ClaimStatus
    meta: Json
    fingerprint: str


class EventConceptRow(NorthvaineModel):
    id: UUID
    parent_id: UUID | None
    level: int = Field(ge=0)
    label: str = Field(pattern=SNAKE)
    description: str
    embedding: list[float] | None
    status: ConceptStatus
    merged_into: UUID | None
    created_at: datetime


class EventRow(NorthvaineModel):
    id: UUID
    company_id: UUID | None
    event_type: str
    occurred_on: date | None
    details: Json
    cluster_id: UUID | None
    claim_ids: list[UUID]
    created_at: datetime
    concept_id: UUID | None
    slots: Json
    available_at: datetime | None
    description: str | None
    embedding: list[float] | None
    fingerprint: str


# ============ PRIVATE LAYER ============


class BusinessProfileRow(NorthvaineModel):
    workspace_id: UUID
    version: int
    schema_ver: str
    profile: Json
    created_at: datetime


class ProductRow(NorthvaineModel):
    id: UUID
    workspace_id: UUID | None
    sku: str | None
    name: str
    hs_code: str | None
    attributes: Json
    public: bool


class WorkspaceCompanyRow(NorthvaineModel):
    workspace_id: UUID
    company_id: UUID
    relation: WorkspaceRelation
    owner_user: UUID | None


# ============ LEARNING ============


class HypothesisRow(NorthvaineModel):
    id: UUID
    workspace_id: UUID | None
    learner: Learner
    kind: str = Field(pattern=SNAKE)
    parent_id: UUID | None
    body: Json
    schema_ver: str
    status: HypothesisStatus
    origin: HypothesisOrigin
    proposed_at: datetime
    tests: JsonDoc
    decided_at: datetime | None
    strategy_version: int


class ThesisRow(NorthvaineModel):
    id: UUID
    workspace_id: UUID | None
    name: str
    spec: Json
    origin: ThesisOrigin
    pinned: bool
    status: ThesisStatus
    embedding: list[float] | None
    created_at: datetime


class CaseRow(NorthvaineModel):
    id: UUID
    workspace_id: UUID | None
    company_id: UUID | None
    direction: CaseDirection
    thesis_id: UUID | None
    pattern_id: UUID | None
    stage: CaseStage
    verdict: Json | None
    window_start: date | None
    window_end: date | None
    assigned_to: UUID | None
    trace: JsonDoc
    created_at: datetime
    updated_at: datetime


class CaseEvidenceRow(NorthvaineModel):
    case_id: UUID
    claim_id: UUID
    stance: EvidenceStance


class ContactRow(NorthvaineModel):
    id: UUID
    company_id: UUID | None
    role: str
    name: str | None
    email: str | None
    claim_id: UUID | None
    verified: bool
    workspace_id: UUID | None


class MessageRow(NorthvaineModel):
    id: UUID
    case_id: UUID | None
    direction: MessageDirection
    channel: str
    counterpart: Counterpart
    agent_domain: str | None
    subject: str | None
    body: str
    status: MessageStatus
    approved_by: UUID | None
    classification: str | None
    created_at: datetime


class QuoteRequestRow(NorthvaineModel):
    id: UUID
    case_id: UUID | None
    items: JsonDoc
    destination: str | None
    needed_by: date | None
    notes: str | None
    reply_due_at: datetime | None
    answered_at: datetime | None


class FeedbackRow(NorthvaineModel):
    id: UUID
    case_id: UUID | None
    user_id: UUID | None
    rating: FeedbackRating
    reason: str | None
    created_at: datetime


class OutcomeRow(NorthvaineModel):
    case_id: UUID
    stage: CaseStage
    value: Decimal | None
    currency: str | None = Field(pattern=r"^[A-Z]{3}$")  # ISO 4217
    recorded_at: datetime


class StrategyVersionRow(NorthvaineModel):
    workspace_id: UUID
    version: int
    snapshot: Json
    changes: JsonDoc
    created_at: datetime


class QuestionRow(NorthvaineModel):
    id: UUID
    workspace_id: UUID | None
    question: str
    reason: str
    status: QuestionStatus
    answer: str | None
    asked_at: datetime | None


class PlaybookRow(NorthvaineModel):
    id: UUID
    workspace_id: UUID
    hypothesis_id: UUID | None
    thesis_id: UUID | None
    name: str
    spec: Json
    schema_ver: str
    status: PlaybookStatus
    pinned: bool
    created_at: datetime


class SearchProgramRow(NorthvaineModel):
    id: UUID
    workspace_id: UUID | None
    source_hypothesis: UUID | None
    name: str
    templates: JsonDoc
    sources: JsonDoc
    filters: Json
    schedule: Json
    status: ProgramStatus
    yields: Json
    schema_ver: str
    created_at: datetime
    updated_at: datetime


class ExpectationRow(NorthvaineModel):
    id: UUID
    workspace_id: UUID | None
    company_id: UUID
    concept_id: UUID
    hypothesis_id: UUID | None
    window_start: date
    window_end: date
    origin: Learner
    status: ExpectationStatus
    value: Decimal | None
    met_event_id: UUID | None
    created_at: datetime
    resolved_at: datetime | None

    @model_validator(mode="after")
    def _window_is_ordered(self) -> ExpectationRow:
        if self.window_end < self.window_start:
            raise ValueError("window_end must be on or after window_start")
        return self


class BeliefRow(NorthvaineModel):
    id: int
    learner: Learner
    workspace_id: UUID | None
    strategy_version: int
    kind: str = Field(pattern=SNAKE)
    key: str
    params: Json
    schema_ver: str
    n_evidence: float = Field(ge=0)
    prior_source: str | None
    updated_at: datetime


class BeliefSourceCalibrationRow(NorthvaineModel):
    id: int
    workspace_id: UUID | None
    learner: Learner
    prior_source: str
    bias: float
    spread: float = Field(gt=0)
    n_pairs: int = Field(ge=0)
    strategy_version: int
    updated_at: datetime


class PolicyParamRow(NorthvaineModel):
    id: int
    workspace_id: UUID | None
    name: str = Field(pattern=r"^[a-z][a-z0-9_.]*$")
    default_value: Any  # a threshold may be a scalar, so not limited to objects
    current_value: Any
    update_rule: str
    metric: str
    strategy_version: int
    updated_at: datetime


class DecisionRow(NorthvaineModel):
    id: int
    workspace_id: UUID | None
    kind: DecisionKind
    case_id: UUID | None
    company_id: UUID | None
    features: Json
    choice: Json
    value_estimate: float | None
    propensity: float = Field(gt=0, le=1)
    cost_usd: Decimal
    strategy_version: int
    created_at: datetime


class FailureAttributionRow(NorthvaineModel):
    id: UUID
    feedback_id: UUID
    code: str = Field(pattern=SNAKE)
    learner: Learner
    component: str
    target_id: str | None
    weight: float = Field(gt=0, le=1)
    confirmed: bool
    created_at: datetime


class MissedOpportunityRow(NorthvaineModel):
    id: UUID
    workspace_id: UUID
    source: MissedSource
    company_id: UUID | None
    case_id: UUID | None
    occurred_on: date
    evidence_claim_id: UUID | None
    postmortem_status: PostmortemStatus
    postmortem: Json
    created_at: datetime
    analyzed_at: datetime | None


class ControlRow(NorthvaineModel):
    id: UUID
    workspace_id: UUID
    hypothesis_id: UUID | None
    positive_company_id: UUID
    control_company_id: UUID
    as_of: date
    match_on: Json
    created_at: datetime

    @model_validator(mode="after")
    def _companies_differ(self) -> ControlRow:
        if self.positive_company_id == self.control_company_id:
            raise ValueError("positive and control company must differ")
        return self


class LessonRow(NorthvaineModel):
    id: UUID
    workspace_id: UUID
    strategy_version: int
    learner: Learner
    body: str
    belief_change: Json
    behaviour_change: Json
    created_at: datetime


class InboundQueryRow(NorthvaineModel):
    id: UUID
    workspace_id: UUID
    channel: str
    counterpart: Counterpart
    agent_domain: str | None
    query: str
    answered: bool
    case_id: UUID | None
    cluster_id: UUID | None
    created_at: datetime


class CaseOpenQuestionRow(NorthvaineModel):
    id: UUID
    case_id: UUID
    question: str
    source_learner: Learner
    hypothesis_id: UUID | None
    status: OpenQuestionStatus
    answer_claim_id: UUID | None
    created_at: datetime
    resolved_at: datetime | None


# ============ OPERATIONS ============

JobRow = Job


class ModelTier(StrEnum):
    """Routing tier for an LLM call (ARCHITECTURE §20)."""

    FAST = "fast"
    MID = "mid"
    DEEP = "deep"
    EMBED = "embed"


class BudgetKind(StrEnum):
    """Which of the four money caps `brain/budget.py` checks (DECISIONS D1)."""

    CALL = "call"
    RUN = "run"
    DAY = "day"
    TOTAL = "total"


class LlmUsage(NorthvaineModel):
    """Token counts of one completion or embedding call, as reported by Token Factory."""

    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)


class ModelPrice(NorthvaineModel):
    """One `pricing.json` entry: per-million USD prices and the model's context window.

    `checked_on` and `source_url` trace the figure back to the research that confirmed it
    (CLAUDE.md "never guess model ids, parameters, or endpoints"). Token Factory exposes no
    `max_output_tokens`, only `context_length` (docs/integrations/nebius-token-factory-api-
    surface-and-client.md, probe P1), so `context_length` is what a caller's `max_tokens` is
    validated against.
    """

    model: str
    usd_per_million_input: Decimal = Field(ge=0)
    usd_per_million_output: Decimal | None = Field(default=None, ge=0)
    context_length: int = Field(gt=0)
    checked_on: date
    source_url: str


T = TypeVar("T", bound=BaseModel)


class LlmResult(NorthvaineModel, Generic[T]):
    """The validated result of one `brain/llm.py` call: the typed value, usage and cost."""

    value: T
    usage: LlmUsage
    cost_usd: Decimal
    model: str


class LlmCallRow(NorthvaineModel):
    id: int
    workspace_id: UUID | None
    case_id: UUID | None
    model: str
    purpose: str
    input_tokens: int | None
    output_tokens: int | None
    cost_usd: Decimal | None
    ok: bool | None
    run_id: UUID | None
    prompt_version: str | None
    latency_ms: int | None
    error: str | None
    provider: str
    created_at: datetime


class AuditLogRow(NorthvaineModel):
    id: int
    workspace_id: UUID | None
    actor: str
    action: str
    target: str | None
    details: Json | None
    created_at: datetime


# ---------------------------------------------------------------------------
# M4 (evidence ledger, factory/board/M4/PLAN.md "Frozen contracts"). Plain values passed between
# radar/ and core/ledger.py; none of them is a table row.
# ---------------------------------------------------------------------------

Iso2 = Annotated[str, Field(pattern=r"^[A-Z]{2}$")]
SnakeCase = Annotated[str, Field(pattern=SNAKE)]


class EvidenceKind(StrEnum):
    """How a document may be used as evidence (D45)."""

    STRUCTURED = "structured"
    FULL_TEXT = "full_text"
    LEAD = "lead"


class QuoteMode(StrEnum):
    """`extracted`: normalized exact then fuzzy. `structured`: one whole line, exact (D48)."""

    EXTRACTED = "extracted"
    STRUCTURED = "structured"


class Eligibility(NorthvaineModel):
    kind: EvidenceKind
    reason: str | None = None


class EvidenceDocument(NorthvaineModel):
    id: UUID
    source_name: str
    url: str
    title: str | None = None
    text: str
    available_at: datetime | None = None
    workspace_id: UUID | None = None
    group_key: str | None = None
    meta: dict[str, Any] = Field(default_factory=dict)


class SubjectMention(NorthvaineModel):
    name: str
    country: Iso2 | None = None
    role: SnakeCase


class ClaimDraft(NorthvaineModel):
    statement: str
    source_quote: str
    subject: SubjectMention | None = None
    extracted_by: str
    meta: dict[str, Any] = Field(default_factory=dict)


class QuoteMatch(NorthvaineModel):
    found: bool
    offset: int | None = None
    length: int | None = None
    ratio: float
    method: Literal["exact", "line", "fuzzy"] | None = None
    reason: ClaimStatus | None = None


class ClaimCheck(NorthvaineModel):
    document_id: UUID
    draft: ClaimDraft
    status: ClaimStatus
    quote_offset: int | None = None
    verified_by: str | None = None
    fingerprint: str

    @property
    def verified(self) -> bool:
        return self.status == ClaimStatus.VERIFIED


class EventDraft(NorthvaineModel):
    event_type: str
    claim_indices: list[int]
    subject: SubjectMention | None = None
    date_text: str | None = None
    occurred_on: date | None = None
    group_key: str | None = None
    slots: dict[str, Any] = Field(default_factory=dict)
    concept_label: str | None = None
    concept_hint: str | None = None


class ConceptAssignment(NorthvaineModel):
    concept_id: UUID | None = None
    parent_id: UUID | None = None
    level: int = Field(ge=0)
    label: str
    description: str
    status: str
    is_new: bool
    embedding: list[float] | None = None


class ClusterCandidate(NorthvaineModel):
    event_id: UUID | None = None
    cluster_id: UUID
    event_type: str
    occurred_on: date | None = None
    subject_key: str | None = None
    group_key: str | None = None
    embedding: list[float] | None = None
    available_at: datetime | None = None


class PendingEvent(NorthvaineModel):
    event_type: str
    claim_fingerprints: list[str]
    occurred_on: date | None = None
    available_at: datetime | None = None
    subject: SubjectMention | None = None
    description: str
    embedding: list[float] | None = None
    concept: ConceptAssignment
    cluster_id: UUID
    slots: dict[str, Any] = Field(default_factory=dict)
    details: dict[str, Any] = Field(default_factory=dict)
    fingerprint: str


class NewEvent(NorthvaineModel):
    """What `core.ledger.save_events` takes: a PendingEvent with stored claim ids."""

    event_type: str
    claim_ids: list[UUID]
    occurred_on: date | None = None
    available_at: datetime | None = None
    subject: SubjectMention | None = None
    description: str
    embedding: list[float] | None = None
    concept_id: UUID | None = None
    cluster_id: UUID
    slots: dict[str, Any] = Field(default_factory=dict)
    details: dict[str, Any] = Field(default_factory=dict)
    fingerprint: str


class VerifiedClaim(NorthvaineModel):
    id: UUID
    document_id: UUID
    statement: str
    source_quote: str
    quote_offset: int
    verified_by: str
    available_at: datetime | None = None
    workspace_id: UUID | None = None
    meta: dict[str, Any] = Field(default_factory=dict)


class LedgerResult(NorthvaineModel):
    document_id: UUID
    eligibility: Eligibility
    checks: list[ClaimCheck] = Field(default_factory=list)
    events: list[PendingEvent] = Field(default_factory=list)
    llm_calls: int = 0
