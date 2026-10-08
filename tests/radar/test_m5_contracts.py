"""M5 radar contracts (T5.0): names import, signatures match PLAN.md, validators hold, the run
record round-trips and the two LLM output schemas stay inside the PF1-confirmed keywords.
Shape only: no test asserts a skeleton raises.
"""

from __future__ import annotations

import inspect
import subprocess
import sys
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from northvaine.core.models import EvidenceKind
from northvaine.radar import brief, court, discover, entities, gate, run
from northvaine.radar.models import (
    AgainstPoint,
    Candidate,
    CandidateClaim,
    CandidateEvent,
    ClientSpec,
    GateDecision,
    RadarRun,
    RadarStream,
    RankedEntry,
    RejectedAs,
    RejectedEntry,
    SkepticFinding,
    UpgradedPage,
    load_client_spec,
    stream_is_enumerable,
)
from northvaine.sensors.base import SensorQuery
from tests.radar.test_output_schemas import ALLOWED, FORBIDDEN, keywords

REPO = Path(__file__).resolve().parents[2]
CLIENTS = REPO / "tests" / "fixtures" / "clients"
NOW = datetime(2026, 10, 5, 9, 0, tzinfo=UTC)


def params(fn: object) -> list[str]:
    return list(inspect.signature(fn).parameters)  # type: ignore[arg-type]


def kind(fn: object, name: str) -> inspect._ParameterKind:
    return inspect.signature(fn).parameters[name].kind  # type: ignore[arg-type]


# --- streams and rejection reasons -------------------------------------------------------


def test_stream_values_and_enumerability() -> None:
    assert [s.value for s in RadarStream] == ["tender", "award", "announcement"]
    assert stream_is_enumerable(RadarStream.TENDER)
    assert stream_is_enumerable(RadarStream.AWARD)
    assert not stream_is_enumerable(RadarStream.ANNOUNCEMENT)
    assert stream_is_enumerable("tender")


def test_rejected_as_values() -> None:
    assert {r.value for r in RejectedAs} == {
        "unidentified",
        "insufficient_evidence",
        "competitor",
        "reseller",
        "publisher",
        "not_a_buyer",
        "not_an_organisation",
    }


# --- signatures --------------------------------------------------------------------------


def test_signatures_match_the_plan() -> None:
    assert params(load_client_spec) == ["client_id", "clients_dir"]
    assert params(discover.shift_queries) == ["queries", "as_of"]
    assert params(discover.strip_contacts) == ["text"]
    assert params(discover.upgraded_document) == ["page", "lead"]
    assert params(discover.discover) == ["spec", "queries", "http", "fetcher", "settings"]
    assert params(discover.PageFetcher.fetch) == ["self", "url"]
    assert params(discover.LivePageFetcher.fetch) == ["self", "url"]
    assert params(discover.RecordedPageFetcher.fetch) == ["self", "url"]
    assert params(entities.company_key) == ["name", "country", "settings"]
    assert params(entities.stream_for) == ["source_name", "event_type", "settings"]
    assert params(entities.window_for) == ["stream", "events", "settings"]
    assert params(entities.build_candidates) == ["results", "settings"]
    assert params(gate.numbers_grounded) == ["text", "quotes"]
    assert params(gate.gate_candidate) == ["candidate", "spec", "run", "session", "settings"]
    assert params(court.skeptic) == ["candidate", "gate", "spec", "run", "session", "settings"]
    assert params(brief.rank) == [
        "passed",
        "as_of",
        "settings",
        "offer",
        "terms",
        "related_terms",
    ]  # fmt: skip  (D80, D82, D84)
    assert params(brief.render_brief) == ["run"]
    assert params(brief.render_scorecard) == ["run"]
    assert params(brief.write_reports) == ["run", "out_dir"]
    assert params(run.seeded_concepts) == []
    assert params(run.run_radar) == [
        "spec",
        "as_of",
        "http",
        "fetcher",
        "concepts",
        "run",
        "settings",
        "session",
    ]  # fmt: skip  (session added by D69: a live run logs every call in llm_calls)


def test_keyword_only_parameters() -> None:
    only = inspect.Parameter.KEYWORD_ONLY
    assert kind(discover.discover, "http") is only
    assert kind(discover.discover, "fetcher") is only
    assert kind(entities.build_candidates, "settings") is only
    assert kind(gate.gate_candidate, "run") is only
    assert kind(court.skeptic, "run") is only
    assert kind(brief.rank, "as_of") is only
    assert kind(run.run_radar, "as_of") is only
    assert kind(run.run_radar, "concepts") is only


# --- builders ----------------------------------------------------------------------------


def make_claim(ref: str = "C1") -> CandidateClaim:
    return CandidateClaim(
        ref=ref,
        fingerprint="fp1",
        document_id=uuid4(),
        statement="Acme Works plans a new plaza.",
        source_quote="Acme Works plans a new plaza in the town centre.",
        source_name="tavily",
        url="https://example.com/news/1",
        available_at=NOW,
        evidence_kind=EvidenceKind.FULL_TEXT,
        verified_by="quote_and_support",
        upgraded_from=None,
    )


def make_candidate() -> Candidate:
    return Candidate(
        key="acme works|GB",
        name="Acme Works Ltd",
        country="GB",
        aliases=["Acme Works"],
        roles=["buyer"],
        stream=RadarStream.ANNOUNCEMENT,
        streams=[RadarStream.ANNOUNCEMENT],
        events=[
            CandidateEvent(
                event_type="project_announced",
                description="A new plaza",
                occurred_on=date(2026, 9, 30),
                available_at=NOW,
                claim_refs=["C1"],
                slots={"area": 1200},
                fingerprint="ev1",
            )
        ],
        claims=[make_claim()],
        window_start=None,
        window_end=None,
        window_estimated=False,
        window_note="date as stated",
    )


def make_gate(passed: bool = True) -> GateDecision:
    return GateDecision(
        passed=passed,
        rejected_as=None if passed else RejectedAs.PUBLISHER,
        by="llm",
        reason="a direct buyer" if passed else "a news site",
        direct_buyer=True if passed else None,
        buyer_reason="commissions the works" if passed else None,
        demand_reason="new plaza" if passed else None,
        suggested_action="approach the project team" if passed else None,
        cited_refs=["C1"],
    )


def make_run() -> RadarRun:
    candidate = make_candidate()
    return RadarRun(
        client_id="stone_supplier",
        offer="An offer",
        as_of=NOW,
        queries={"tavily": [SensorQuery(text="plaza", countries=["GB"], languages=["en"])]},
        documents_by_kind={"full_text": 1, "lead": 2},
        leads=2,
        upgraded=[
            UpgradedPage(
                lead_url="https://example.com/l",
                final_url=None,
                status=403,
                fetched_at=None,
                title=None,
                text=None,
                refused="http_403",
            )
        ],
        entries=[
            RankedEntry(
                rank=1,
                candidate=candidate,
                gate=make_gate(),
                skeptic=SkepticFinding(
                    stance="against",
                    against=[AgainstPoint(claim_ref="C1", why="may be a feasibility study")],
                    open_questions=["Is funding agreed?"],
                ),
                strength="strong",
                rank_reasons=["verified full text"],
            )
        ],
        rejected=[RejectedEntry(candidate=candidate, gate=make_gate(passed=False))],
        llm_calls=3,
        cost_usd=Decimal("0.0123"),
        notes=["one query dropped"],
    )


# --- validators and round trip -------------------------------------------------------------


def test_gate_decision_rejects_inconsistent_values() -> None:
    good = make_gate().model_dump()
    with pytest.raises(ValidationError):
        GateDecision(**{**good, "rejected_as": RejectedAs.COMPETITOR})
    with pytest.raises(ValidationError):
        GateDecision(**{**good, "passed": False})


def test_skeptic_finding_rejects_inconsistent_values() -> None:
    with pytest.raises(ValidationError):
        SkepticFinding(stance="against", against=[], open_questions=[])
    with pytest.raises(ValidationError):
        SkepticFinding(
            stance="unknown",
            against=[AgainstPoint(claim_ref="C1", why="x")],
            open_questions=[],
        )
    ok = SkepticFinding(stance="unknown", against=[], open_questions=["Who buys?"])
    assert ok.stance == "unknown"


def test_radar_run_round_trips_through_json() -> None:
    original = make_run()
    again = RadarRun.model_validate_json(original.model_dump_json())
    assert again == original
    assert again.entries[0].gate.rejected_as is None
    assert again.rejected[0].gate.rejected_as is RejectedAs.PUBLISHER


# --- LLM output schemas (PF1) -----------------------------------------------------------


def _property_names(node: object) -> list[tuple[dict, list[str]]]:
    """Every object schema under `node` with its property names."""
    found: list[tuple[dict, list[str]]] = []
    if isinstance(node, dict):
        if isinstance(node.get("properties"), dict):
            found.append((node, list(node["properties"])))
        for value in node.values():
            if isinstance(value, dict):
                children = value.values() if node.get("properties") is value else [value]
                for child in children:
                    found += _property_names(child)
            elif isinstance(value, list):
                for item in value:
                    found += _property_names(item)
    return found


@pytest.mark.parametrize("model", [gate.GateOutput, court.SkepticOutput], ids=lambda m: m.__name__)
def test_output_schema_is_strict_safe(model: type) -> None:
    schema = model.model_json_schema()
    used = keywords(schema)
    assert used <= ALLOWED, sorted(used - ALLOWED)
    assert not used & FORBIDDEN
    objects = _property_names(schema)
    assert objects
    for obj, names in objects:
        assert set(obj.get("required", [])) == set(names), names
    assert not model.__doc__


def test_output_schema_limits() -> None:
    gate_props = gate.GateOutput.model_json_schema()["properties"]
    assert gate_props["cited_refs"]["maxItems"] == 8
    sk_props = court.SkepticOutput.model_json_schema()["properties"]
    assert sk_props["against"]["maxItems"] == 4
    assert sk_props["open_questions"]["maxItems"] == 3
    assert not court.SkepticItem.__doc__


# --- client specs ------------------------------------------------------------------------


@pytest.mark.parametrize("path", sorted(CLIENTS.glob("*.json")), ids=lambda p: p.stem)
def test_load_client_spec_reads_every_fixture(path: Path) -> None:
    spec = load_client_spec(path.stem, CLIENTS)
    assert isinstance(spec, ClientSpec)
    assert spec.id == path.stem
    assert spec.sensors
    for queries in spec.sensors.values():
        assert all(isinstance(q, SensorQuery) for q in queries)


def test_three_client_fixtures_exist() -> None:
    assert len(list(CLIENTS.glob("*.json"))) == 3


def test_load_client_spec_default_dir_comes_from_settings() -> None:
    assert load_client_spec("stone_supplier").id == "stone_supplier"


def test_unknown_client_names_the_id() -> None:
    with pytest.raises(FileNotFoundError, match="no_such_client"):
        load_client_spec("no_such_client", CLIENTS)


# --- imports -----------------------------------------------------------------------------


def test_pure_modules_import_no_network_or_llm_sdk() -> None:
    code = (
        "import sys\n"
        "import northvaine.radar.models, northvaine.radar.entities, northvaine.radar.brief\n"
        "for bad in ('httpx', 'openai'):\n"
        "    assert bad not in sys.modules, bad + ' imported'\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        env={"PATH": "", "SYSTEMROOT": "C:\\Windows"} if sys.platform == "win32" else {},
        capture_output=True,
        text=True,
        check=False,
        cwd=REPO,
    )
    assert result.returncode == 0, result.stderr
