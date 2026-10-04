"""T1.6: enums and row models mirroring schema v2."""

from __future__ import annotations

import re
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from northvaine.core import models as m

ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 1, 1, tzinfo=UTC)

STAGES = {
    "candidate",
    "gated",
    "investigated",
    "briefed",
    "approved",
    "contacted",
    "replied",
    "meeting",
    "samples",
    "quoted",
    "won",
    "lost",
    "dismissed",
}
LEARNERS = {"world", "org", "buying", "research", "allocator"}

# Value sets from PLAN.md "Schema v2" and the v1 baseline.
EXPECTED: dict[type[StrEnum], set[str]] = {
    m.MembershipRole: {"owner", "manager", "rep", "ops"},
    m.SourceTier: {"official", "company", "reported", "social", "private", "paid"},
    m.WorkspaceRelation: {"customer", "best_customer", "prospect", "competitor", "suppressed"},
    m.ThesisOrigin: {"generated", "user", "discovered"},
    m.ThesisStatus: {"active", "exploring", "retired"},
    m.CaseDirection: {"outbound", "inbound"},
    m.CaseStage: STAGES,
    m.EvidenceStance: {"for", "against", "unknown"},
    m.MessageDirection: {"out", "in"},
    m.Counterpart: {"human", "agent"},
    m.MessageStatus: {"draft", "approved", "sent", "received"},
    m.FeedbackRating: {"good", "not_relevant", "wrong_facts", "later"},
    m.QuestionStatus: {"pending", "asked", "answered", "skipped"},
    m.JobStatus: {"queued", "running", "done", "failed"},
    m.Learner: LEARNERS,
    m.ConceptStatus: {"active", "proposed", "merged", "retired"},
    m.HypothesisStatus: {
        "proposed",
        "exploring",
        "exploiting",
        "degraded",
        "retired",
        "rejected",
    },
    m.HypothesisOrigin: {
        "llm_prior",
        "history_mining",
        "world_lift",
        "error_driven",
        "missed_opportunity",
        "cross_org",
        "owner",
    },
    m.PlaybookStatus: {"active", "exploring", "retired"},
    m.ProgramStatus: {"active", "trial", "paused", "retired"},
    m.ExpectationStatus: {"pending", "met", "missed"},
    m.DecisionKind: {"brief", "search", "investigation", "question"},
    m.MissedSource: {"inbound", "win", "public_award"},
    m.PostmortemStatus: {
        "pending",
        "not_surfaced",
        "surfaced_dropped",
        "surfaced_late",
        "surfaced_in_time",
    },
    m.OpenQuestionStatus: {"open", "answered", "dropped"},
}


@pytest.mark.parametrize("enum_cls", list(EXPECTED), ids=lambda c: c.__name__)
def test_enum_values_match_plan(enum_cls: type[StrEnum]) -> None:
    assert {member.value for member in enum_cls} == EXPECTED[enum_cls]


IRREGULAR = {"hypotheses": "Hypothesis", "theses": "Thesis", "policy_params": "PolicyParam"}


def _singular(table: str) -> str:
    words = table.split("_")
    if table in IRREGULAR:
        return IRREGULAR[table] + "Row"
    last = words[-1]
    if last.endswith("ies"):
        last = last[:-3] + "y"
    elif last.endswith("s") and not last.endswith("ss"):
        last = last[:-1]
    return "".join(w.capitalize() for w in [*words[:-1], last]) + "Row"


def test_every_table_has_a_row_model_and_the_view_has_none() -> None:
    sql = (ROOT / "schema.sql").read_text(encoding="utf-8")
    tables = re.findall(r"^CREATE TABLE (\w+)", sql, flags=re.M)
    assert len(tables) >= 39
    for table in tables:
        name = _singular(table)
        if table == "audit_log":
            name = "AuditLogRow"
        if table == "llm_calls":
            name = "LlmCallRow"
        assert hasattr(m, name), f"{table} -> {name}"
    assert m.JobRow is m.Job
    assert not hasattr(m, "PatternRow")


def test_nullability_examples() -> None:
    # A nullable column accepts None, a NOT NULL column rejects it.
    assert _case().verdict is None
    with pytest.raises(ValidationError):
        m.CaseRow(**{**_case_data(), "stage": None})  # type: ignore[arg-type]


def test_unknown_field_is_rejected() -> None:
    with pytest.raises(ValidationError):
        m.WorkspaceRow(id=uuid4(), name="x", primary_domain=None, created_at=NOW, extra=1)


def _case_data() -> dict[str, object]:
    return {
        "id": uuid4(),
        "workspace_id": uuid4(),
        "company_id": None,
        "direction": "inbound",
        "thesis_id": None,
        "pattern_id": None,
        "stage": "candidate",
        "verdict": None,
        "window_start": None,
        "window_end": None,
        "assigned_to": None,
        "trace": [],
        "created_at": NOW,
        "updated_at": NOW,
    }


def _case() -> m.CaseRow:
    return m.CaseRow(**_case_data())  # type: ignore[arg-type]


def _company(**over: object) -> dict[str, object]:
    data: dict[str, object] = {
        "id": uuid4(),
        "primary_domain": None,
        "name": "Acme",
        "aliases": [],
        "country": "DE",
        "locality": None,
        "industry_codes": [],
        "attributes": {},
        "updated_at": NOW,
    }
    return {**data, **over}


def _outcome(**over: object) -> dict[str, object]:
    data: dict[str, object] = {
        "case_id": uuid4(),
        "stage": "won",
        "value": Decimal("10.5"),
        "currency": "EUR",
        "recorded_at": NOW,
    }
    return {**data, **over}


def _decision(**over: object) -> dict[str, object]:
    data: dict[str, object] = {
        "id": 1,
        "workspace_id": None,
        "kind": "brief",
        "case_id": None,
        "company_id": None,
        "features": {},
        "choice": {},
        "value_estimate": None,
        "propensity": 0.5,
        "cost_usd": Decimal("0"),
        "strategy_version": 0,
        "created_at": NOW,
    }
    return {**data, **over}


def _attribution(**over: object) -> dict[str, object]:
    data: dict[str, object] = {
        "id": uuid4(),
        "feedback_id": uuid4(),
        "code": "wrong_region",
        "learner": "org",
        "component": "gate",
        "target_id": None,
        "weight": 1.0,
        "confirmed": False,
        "created_at": NOW,
    }
    return {**data, **over}


def _concept(**over: object) -> dict[str, object]:
    data: dict[str, object] = {
        "id": uuid4(),
        "parent_id": None,
        "level": 0,
        "label": "facility_opened",
        "description": "d",
        "embedding": None,
        "status": "active",
        "merged_into": None,
        "created_at": NOW,
    }
    return {**data, **over}


def _hypothesis(**over: object) -> dict[str, object]:
    data: dict[str, object] = {
        "id": uuid4(),
        "workspace_id": None,
        "learner": "world",
        "kind": "pattern",
        "parent_id": None,
        "body": {},
        "schema_ver": "1",
        "status": "proposed",
        "origin": "owner",
        "proposed_at": NOW,
        "tests": [],
        "decided_at": None,
        "strategy_version": 0,
    }
    return {**data, **over}


def _belief(**over: object) -> dict[str, object]:
    data: dict[str, object] = {
        "id": 1,
        "learner": "org",
        "workspace_id": None,
        "strategy_version": 0,
        "kind": "rate",
        "key": "k",
        "params": {},
        "schema_ver": "1",
        "n_evidence": 0.0,
        "prior_source": None,
        "updated_at": NOW,
    }
    return {**data, **over}


def _expectation(**over: object) -> dict[str, object]:
    data: dict[str, object] = {
        "id": uuid4(),
        "workspace_id": None,
        "company_id": uuid4(),
        "concept_id": uuid4(),
        "hypothesis_id": None,
        "window_start": date(2026, 1, 1),
        "window_end": date(2026, 2, 1),
        "origin": "world",
        "status": "pending",
        "value": None,
        "met_event_id": None,
        "created_at": NOW,
        "resolved_at": None,
    }
    return {**data, **over}


def test_country_is_two_uppercase_letters() -> None:
    assert m.CompanyRow(**_company(country="DE")).country == "DE"  # type: ignore[arg-type]
    assert m.CompanyRow(**_company(country=None)).country is None  # type: ignore[arg-type]
    for bad in ("de", "DEU", "D", "D1"):
        with pytest.raises(ValidationError):
            m.CompanyRow(**_company(country=bad))  # type: ignore[arg-type]


def test_currency_is_three_uppercase_letters() -> None:
    assert m.OutcomeRow(**_outcome(currency="EUR")).currency == "EUR"  # type: ignore[arg-type]
    for bad in ("eur", "EU", "EURO"):
        with pytest.raises(ValidationError):
            m.OutcomeRow(**_outcome(currency=bad))  # type: ignore[arg-type]


def test_propensity_in_zero_exclusive_one_inclusive() -> None:
    for ok in (0.0001, 0.5, 1.0):
        assert m.DecisionRow(**_decision(propensity=ok)).propensity == ok  # type: ignore[arg-type]
    for bad in (0, 0.0, -0.1, 1.01):
        with pytest.raises(ValidationError):
            m.DecisionRow(**_decision(propensity=bad))  # type: ignore[arg-type]


def test_weight_in_zero_exclusive_one_inclusive() -> None:
    for ok in (0.01, 1.0):
        assert m.FailureAttributionRow(**_attribution(weight=ok)).weight == ok  # type: ignore[arg-type]
    for bad in (0, -1, 1.5):
        with pytest.raises(ValidationError):
            m.FailureAttributionRow(**_attribution(weight=bad))  # type: ignore[arg-type]


def test_label_is_lowercase_snake_case() -> None:
    assert m.EventConceptRow(**_concept(label="a_b2")).label == "a_b2"  # type: ignore[arg-type]
    for bad in ("Facility", "1abc", "a-b", "a b", "_a", ""):
        with pytest.raises(ValidationError):
            m.EventConceptRow(**_concept(label=bad))  # type: ignore[arg-type]


def test_kind_is_lowercase_snake_case() -> None:
    assert m.HypothesisRow(**_hypothesis(kind="concept_split")).kind == "concept_split"  # type: ignore[arg-type]
    assert m.BeliefRow(**_belief(kind="rate")).kind == "rate"  # type: ignore[arg-type]
    for bad in ("Pattern", "a-b", "9x"):
        with pytest.raises(ValidationError):
            m.HypothesisRow(**_hypothesis(kind=bad))  # type: ignore[arg-type]
        with pytest.raises(ValidationError):
            m.BeliefRow(**_belief(kind=bad))  # type: ignore[arg-type]


def test_expectation_window_must_not_end_before_it_starts() -> None:
    m.ExpectationRow(**_expectation())  # type: ignore[arg-type]
    same = date(2026, 1, 1)
    m.ExpectationRow(**_expectation(window_start=same, window_end=same))  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        m.ExpectationRow(**_expectation(window_start=date(2026, 2, 1), window_end=same))  # type: ignore[arg-type]


def test_control_companies_must_differ() -> None:
    cid = uuid4()
    base = {
        "id": uuid4(),
        "workspace_id": uuid4(),
        "hypothesis_id": None,
        "positive_company_id": uuid4(),
        "control_company_id": uuid4(),
        "as_of": date(2026, 1, 1),
        "match_on": {},
        "created_at": NOW,
    }
    m.ControlRow(**base)  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        m.ControlRow(**{**base, "positive_company_id": cid, "control_company_id": cid})  # type: ignore[arg-type]


def test_enum_fields_reject_unknown_values() -> None:
    with pytest.raises(ValidationError):
        m.CaseRow(**{**_case_data(), "stage": "nonsense"})  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        m.HypothesisRow(**_hypothesis(learner="nobody"))  # type: ignore[arg-type]


# --- M4 evidence ledger models (T4.0) ----------------------------------------------------------


def test_claim_status_values_equal_the_check_list() -> None:
    assert [s.value for s in m.ClaimStatus] == [
        "pending",
        "verified",
        "quote_not_found",
        "quote_too_short",
        "unsupported",
        "ineligible_document",
    ]


def test_claim_and_event_rows_have_the_new_fields() -> None:
    assert {"status", "meta", "fingerprint"} <= set(m.ClaimRow.model_fields)
    assert {"available_at", "description", "embedding", "fingerprint"} <= set(
        m.EventRow.model_fields
    )


LEDGER_FIELDS = {
    "Eligibility": ["kind", "reason"],
    "EvidenceDocument": [
        "id",
        "source_name",
        "url",
        "title",
        "text",
        "available_at",
        "workspace_id",
        "group_key",
        "meta",
    ],
    "SubjectMention": ["name", "country", "role"],
    "ClaimDraft": ["statement", "source_quote", "subject", "extracted_by", "meta"],
    "QuoteMatch": ["found", "offset", "length", "ratio", "method", "reason"],
    "ClaimCheck": ["document_id", "draft", "status", "quote_offset", "verified_by", "fingerprint"],
    "EventDraft": [
        "event_type",
        "claim_indices",
        "subject",
        "date_text",
        "occurred_on",
        "group_key",
        "slots",
        "concept_label",
        "concept_hint",
    ],
    "ConceptAssignment": [
        "concept_id",
        "parent_id",
        "level",
        "label",
        "description",
        "status",
        "is_new",
        "embedding",
    ],
    "ClusterCandidate": [
        "event_id",
        "cluster_id",
        "event_type",
        "occurred_on",
        "subject_key",
        "group_key",
        "embedding",
        "available_at",
    ],
    "PendingEvent": [
        "event_type",
        "claim_fingerprints",
        "occurred_on",
        "available_at",
        "subject",
        "description",
        "embedding",
        "concept",
        "cluster_id",
        "slots",
        "details",
        "fingerprint",
    ],
    "NewEvent": [
        "event_type",
        "claim_ids",
        "occurred_on",
        "available_at",
        "subject",
        "description",
        "embedding",
        "concept_id",
        "cluster_id",
        "slots",
        "details",
        "fingerprint",
    ],
    "VerifiedClaim": [
        "id",
        "document_id",
        "statement",
        "source_quote",
        "quote_offset",
        "verified_by",
        "available_at",
        "workspace_id",
        "meta",
    ],
    "LedgerResult": ["document_id", "eligibility", "checks", "events", "llm_calls"],
}


@pytest.mark.parametrize("name", list(LEDGER_FIELDS))
def test_ledger_model_fields(name: str) -> None:
    assert list(getattr(m, name).model_fields) == LEDGER_FIELDS[name]


def test_evidence_and_quote_enums() -> None:
    assert {e.value for e in m.EvidenceKind} == {"structured", "full_text", "lead"}
    assert {e.value for e in m.QuoteMode} == {"extracted", "structured"}


def test_subject_mention_checks_country_and_role() -> None:
    assert m.SubjectMention(name="Acme", country="DE", role="buyer").country == "DE"
    assert m.SubjectMention(name="Acme", role="buyer").country is None
    with pytest.raises(ValidationError):
        m.SubjectMention(name="Acme", country="de", role="buyer")
    with pytest.raises(ValidationError):
        m.SubjectMention(name="Acme", country="DE", role="Buyer Co")


def test_claim_check_verified_property() -> None:
    draft = m.ClaimDraft(statement="s", source_quote="q", extracted_by="code")
    base = {"document_id": uuid4(), "draft": draft, "fingerprint": "f"}
    ok = m.ClaimCheck(status=m.ClaimStatus.VERIFIED, quote_offset=0, verified_by="code", **base)
    bad = m.ClaimCheck(status=m.ClaimStatus.UNSUPPORTED, **base)
    assert ok.verified is True and bad.verified is False


def test_ledger_models_reject_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        m.Eligibility(kind="lead", surprise=1)  # type: ignore[call-arg]
