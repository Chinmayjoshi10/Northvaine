"""T5.6: `run_radar` end to end on the recorded M3 sensor fixtures, a fake model and recorded pages.

No network, no database, no `.env`. The sensors replay the TED and Tavily fixtures through
`replay_transport`; publisher pages come from a `RecordedPageFetcher` (every lead refused, so no
unrecorded page text exists); the model is a scripted fake client behind `client_override`. The
fake answers by schema name, so it never depends on prompt wording. Nothing here is saved as a
recording (D53): these are code tests, the real recordings come from Recording R.
"""

from __future__ import annotations

import asyncio
import contextvars
import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from northvaine.brain import llm
from northvaine.brain.budget import RunContext
from northvaine.core.settings import Settings
from northvaine.radar import run as run_module
from northvaine.radar.brief import write_reports
from northvaine.radar.discover import RecordedPageFetcher
from northvaine.radar.models import ClientSpec, RadarRun, UpgradedPage, load_client_spec
from northvaine.radar.run import run_radar, seeded_concepts
from northvaine.sensors.replay import load_exchanges, replay_transport

FIXTURES = Path(__file__).parent.parent / "fixtures"
CLIENTS_DIR = FIXTURES / "clients"
CLIENTS = sorted(p.stem for p in CLIENTS_DIR.glob("*.json"))
AS_OF = datetime(2026, 10, 5, tzinfo=UTC)
MODEL_FAST = "nvidia/Nemotron-3_5-Lightning"
MODEL_MID = "nvidia/nemotron-3-super-120b-a12b"
SETTINGS = Settings(
    _env_file=None,
    ted_min_interval_seconds=0,
    tavily_api_key=SecretStr("replay-only-key-0123"),
    radar_enumerable_max_results=10,  # the M3 recordings hold one page of 10 per query
    radar_bidder_max_queries=0,  # the M3 recordings hold no award searches (D81)
    radar_fit_max_accounts=0,  # nor company-fit searches (D96)
)


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch, clean_settings: None) -> None:
    monkeypatch.setenv("MODEL_FAST", MODEL_FAST)
    monkeypatch.setenv("MODEL_MID", MODEL_MID)
    monkeypatch.setenv("DAILY_BUDGET_USD", "10")
    monkeypatch.setenv("TOTAL_BUDGET_USD", "29")
    llm.get_settings.cache_clear()


# --- the recorded world ----------------------------------------------------------------------


def recorded_world(client_id: str) -> tuple[ClientSpec, list[Any], list[UpgradedPage]]:
    """The client spec cut to the queries that have a recorded fixture, the exchanges in query
    order, and a refused page for every Tavily result (so no page text is invented)."""
    spec = load_client_spec(client_id, CLIENTS_DIR)
    exchanges: list[Any] = []
    pages: list[UpgradedPage] = []
    kept: dict[str, list[Any]] = {}
    for sensor, queries in spec.sensors.items():
        kept[sensor] = []
        for number, query in enumerate(queries, start=1):
            path = FIXTURES / "sensors" / sensor / f"{client_id}_{number}.json"
            if not path.exists():
                continue  # the recorder refused some Tavily responses; only recorded calls replay
            recorded = load_exchanges(path)
            exchanges.extend(recorded)
            kept[sensor].append(query)
            for ex in recorded:
                for item in (ex.body_json or {}).get("results", []):
                    pages.append(
                        UpgradedPage(
                            lead_url=item["url"],
                            final_url=None,
                            status=None,
                            fetched_at=None,
                            title=None,
                            text=None,
                            refused="robots",
                        )
                    )
    return spec.model_copy(update={"sensors": kept}), exchanges, pages


class FakeLlm:
    """Scripted replies by schema name. Gate and skeptic answers follow `self.key`, which the
    spies below set to the candidate being worked on."""

    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []
        self.key = ""
        self.on_gate: Any = None
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _digit(self) -> int:
        return int(hashlib.sha256(self.key.encode()).hexdigest(), 16) % 4

    def reply(self, schema: str) -> dict[str, Any]:
        if schema == "ExtractionOutput":
            return {"claims": [], "events": []}
        if schema == "GateOutput":
            if self._digit() == 0:
                return gate_reply("competitor", cited=["C1"])
            return gate_reply("buyer", cited=["C1"])
        if schema == "SkepticOutput":
            if self._digit() == 1:
                return {
                    "against": [{"claim_ref": "C1", "why": "this is not clearly a buyer"}],
                    "open_questions": [],
                }
            return {"against": [], "open_questions": ["who decides on purchases"]}
        raise AssertionError(f"unscripted schema {schema}")

    async def _create(self, **body: Any) -> Any:
        self.requests.append(body)
        schema = body["response_format"]["json_schema"]["name"]
        if schema == "GateOutput" and self.on_gate is not None:
            self.on_gate()
        message = SimpleNamespace(content=json.dumps(self.reply(schema)))
        usage = SimpleNamespace(prompt_tokens=100, completion_tokens=50, total_tokens=150)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=message, finish_reason="stop")], usage=usage
        )

    def schemas(self) -> list[str]:
        return [r["response_format"]["json_schema"]["name"] for r in self.requests]


def gate_reply(verdict: str, cited: list[str]) -> dict[str, Any]:
    return {
        "what_it_did": "it published a notice",
        "needs_the_offer": "yes, the work needs the offer",
        "verdict": verdict,
        "direct_buyer": True,
        "reason": "the notice names it as the contracting body",
        "buyer_reason": "it buys works and supplies",
        "demand_reason": "a published notice shows a need",
        "suggested_action": "check who runs procurement",
        "cited_refs": cited,
    }


class Spy:
    """Call order of gate and skeptic, and the claim count of each gated candidate."""

    def __init__(self, fake: FakeLlm, monkeypatch: pytest.MonkeyPatch) -> None:
        self.events: list[tuple[str, str]] = []
        self.claims: dict[str, int] = {}
        self.closed: dict[str, bool] = {}
        real_gate, real_skeptic = run_module.gate_candidate, run_module.skeptic

        async def gate(candidate: Any, *args: Any, **kwargs: Any) -> Any:
            fake.key = candidate.key
            self.events.append(("gate", candidate.key))
            self.claims[candidate.key] = len(candidate.claims)
            end = candidate.window_end
            self.closed[candidate.key] = end is None or end < AS_OF.date()
            return await real_gate(candidate, *args, **kwargs)

        async def skeptic(candidate: Any, *args: Any, **kwargs: Any) -> Any:
            fake.key = candidate.key
            self.events.append(("skeptic", candidate.key))
            return await real_skeptic(candidate, *args, **kwargs)

        monkeypatch.setattr(run_module, "gate_candidate", gate)
        monkeypatch.setattr(run_module, "skeptic", skeptic)

    def of(self, kind: str) -> list[str]:
        return [key for k, key in self.events if k == kind]


async def radar(
    client_id: str,
    fake: FakeLlm,
    *,
    run: RunContext | None = None,
    settings: Settings | None = None,
) -> RadarRun:
    spec, exchanges, pages = recorded_world(client_id)
    transport = replay_transport(exchanges, match_body=False)  # queries are shifted to AS_OF
    async with httpx.AsyncClient(transport=transport) as http:
        with llm.client_override(fake):
            return await run_radar(
                spec,
                as_of=AS_OF,
                http=http,
                fetcher=RecordedPageFetcher(pages),
                concepts=seeded_concepts(),
                run=run or RunContext(),
                settings=settings or SETTINGS,
            )


# --- seeded concepts -------------------------------------------------------------------------


def test_seeded_concepts_are_the_level_zero_seed_in_load_order() -> None:
    concepts = seeded_concepts()
    assert len(concepts) == 13
    assert "imports_recorded" in {c.label for c in concepts}  # D102, migration 0007
    assert {c.level for c in concepts} == {0}
    labels = [c.label for c in concepts]
    assert labels == sorted(labels)
    assert all(c.description for c in concepts)
    assert [c.id for c in concepts] == [c.id for c in seeded_concepts()]  # deterministic


# --- the pipeline ----------------------------------------------------------------------------


async def test_every_candidate_is_an_entry_or_a_rejection_and_skeptic_follows_its_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeLlm()
    spy = Spy(fake, monkeypatch)
    result = await radar("stone_supplier", fake)

    gated = spy.of("gate")
    entry_keys = [e.candidate.key for e in result.entries]
    llm_rejected = [r.candidate.key for r in result.rejected if r.gate.by == "llm"]
    code_rejected = [r for r in result.rejected if r.gate.by == "code"]
    assert entry_keys and llm_rejected, "the scripted gate must both pass and reject someone"
    assert sorted(entry_keys + llm_rejected) == sorted(gated)
    assert len(set(gated)) == len(gated), "a candidate is gated once"
    assert all(r.gate.rejected_as is not None for r in result.rejected)
    assert all(e.gate.passed for e in result.entries)
    assert all(r.gate.by == "code" for r in code_rejected)

    # skeptic: only for passed candidates, each after its own gate, exactly once
    assert sorted(spy.of("skeptic")) == sorted(entry_keys)
    for key in entry_keys:
        assert spy.events.index(("gate", key)) < spy.events.index(("skeptic", key))
    assert all(e.skeptic.stance in ("against", "unknown") for e in result.entries)
    assert {e.skeptic.stance for e in result.entries} == {"against", "unknown"}
    assert [e.rank for e in result.entries] == list(range(1, len(result.entries) + 1))

    # the run record
    assert result.client_id == "stone_supplier"
    assert result.as_of == AS_OF
    assert result.queries["ted"][0].published_to == AS_OF.date()
    assert result.documents_by_kind["structured"] > 0
    assert result.leads == 2
    assert all(p.refused == "robots" for p in result.upgraded)
    assert result.llm_calls == len(fake.requests)
    assert result.cost_usd > Decimal("0")
    assert fake.schemas().count("GateOutput") == len(gated)


async def test_gate_order_is_most_claims_first_then_key(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeLlm()
    spy = Spy(fake, monkeypatch)
    await radar("stone_supplier", fake)
    # open tender windows first (D71), then most claims, then key
    order = [(spy.closed[k], -spy.claims[k], k) for k in spy.of("gate")]
    assert order == sorted(order)


async def test_the_gate_cap_turns_the_rest_into_a_note(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeLlm()
    spy = Spy(fake, monkeypatch)
    capped = SETTINGS.model_copy(update={"radar_max_gate_candidates": 2})
    result = await radar("stone_supplier", fake, settings=capped)
    assert len(spy.of("gate")) == 2
    assert any("not gated: cap of 2 reached" in n for n in result.notes)


@pytest.mark.parametrize("client_id", CLIENTS)
async def test_the_same_loop_runs_for_every_client(
    client_id: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fake = FakeLlm()
    spy = Spy(fake, monkeypatch)
    result = await radar(client_id, fake)
    assert result.client_id == client_id
    assert sorted(spy.of("skeptic")) == sorted(e.candidate.key for e in result.entries)
    assert result.leads >= 1
    paths = write_reports(result, tmp_path)  # a brief is written for every client
    assert [p.name for p in paths] == ["brief.md", "scorecard.md", "run.json"]
    assert all(p.read_text(encoding="utf-8").strip() for p in paths)


async def test_packaging_without_ted_queries_still_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    spec, _, _ = recorded_world("packaging_supplier")
    assert not spec.sensors.get("ted")
    fake = FakeLlm()
    spy = Spy(fake, monkeypatch)
    result = await radar("packaging_supplier", fake)
    assert result.entries == [] and result.rejected == []
    assert spy.events == []
    assert result.documents_by_kind == {}


def test_run_module_names_no_client_and_no_industry() -> None:
    source = Path(run_module.__file__).read_text(encoding="utf-8").lower()
    for client_id in CLIENTS:
        assert client_id.lower() not in source
        assert client_id.split("_")[0].lower() not in source


# --- budget ----------------------------------------------------------------------------------


async def test_gates_run_concurrently_and_the_record_keeps_the_gate_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    working_on: contextvars.ContextVar[str] = contextvars.ContextVar("working_on", default="")

    class PerTask(FakeLlm):
        """Answers follow the candidate of the calling task, so concurrent calls cannot swap
        answers (a shared `key` would be overwritten by the next gate)."""

        async def _create(self, **body: Any) -> Any:
            self.key = working_on.get()
            return await super()._create(**body)

    async def outcome(concurrency: int) -> tuple[int, list[str], list[str]]:
        fake = PerTask()
        real_gate, real_skeptic = run_module.gate_candidate, run_module.skeptic
        flight = {"now": 0, "most": 0}

        async def gate(candidate: Any, *args: Any, **kwargs: Any) -> Any:
            working_on.set(candidate.key)  # each gate runs in its own task
            flight["now"] += 1
            flight["most"] = max(flight["most"], flight["now"])
            await asyncio.sleep(0.01)  # a network call: the other gates get their turn
            flight["now"] -= 1
            return await real_gate(candidate, *args, **kwargs)

        monkeypatch.setattr(run_module, "gate_candidate", gate)
        monkeypatch.setattr(run_module, "skeptic", real_skeptic)
        settings = SETTINGS.model_copy(update={"radar_gate_concurrency": concurrency})
        result = await radar("stone_supplier", fake, settings=settings)
        return (
            flight["most"],
            [e.candidate.key for e in result.entries],
            [r.candidate.key for r in result.rejected],
        )

    one = await outcome(1)
    many = await outcome(4)
    assert one[0] == 1 and many[0] > 1
    assert many[1:] == one[1:]


async def test_a_run_over_budget_after_the_first_gate_stops_with_a_note_and_a_brief(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    run = RunContext()
    fake = FakeLlm()
    fake.on_gate = lambda: setattr(run, "spent_usd", Decimal("2"))  # past the 1.00 cap
    spy = Spy(fake, monkeypatch)
    result = await radar("stone_supplier", fake, run=run)
    assert len(spy.of("gate")) == 1
    assert any("run budget" in n for n in result.notes)
    assert any("not gated: run budget reached" in n for n in result.notes)
    assert result.cost_usd >= Decimal("2")
    paths = write_reports(result, tmp_path)
    assert "run budget" in paths[0].read_text(encoding="utf-8")
    assert all(p.stat().st_size > 0 for p in paths)


async def test_a_run_already_over_budget_reads_and_gates_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fake = FakeLlm()
    spy = Spy(fake, monkeypatch)
    result = await radar("stone_supplier", fake, run=RunContext(spent_usd=Decimal("5")))
    assert fake.requests == [] and spy.events == []
    assert result.entries == []
    assert any("not read" in n for n in result.notes)
    assert all(p.stat().st_size > 0 for p in write_reports(result, tmp_path))


async def test_a_document_the_model_cannot_answer_is_skipped_with_a_note(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from northvaine.brain.errors import LlmInvalidOutput

    real = run_module.build_evidence
    failed: list[str] = []

    async def flaky(doc: Any, *args: Any, **kwargs: Any) -> Any:
        if not failed:
            failed.append(doc.url)
            raise LlmInvalidOutput("truncated output")
        return await real(doc, *args, **kwargs)

    monkeypatch.setattr(run_module, "build_evidence", flaky)
    result = await radar("stone_supplier", FakeLlm())
    assert failed and any(
        f"document skipped (LlmInvalidOutput): {failed[0]}" in n for n in result.notes
    )
    assert result.entries or result.rejected  # the run went on past the bad document
