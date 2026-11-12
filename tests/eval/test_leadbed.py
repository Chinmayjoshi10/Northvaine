"""The lead test bed scorer: rule checks, judge combination, cache and summary. No network."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from northvaine.eval.leadbed import (
    JudgeCache,
    JudgeOutput,
    Rules,
    cache_key,
    lead_facts,
    rule_points,
    score_run,
    summarise,
)
from northvaine.radar.models import (
    Candidate,
    CandidateClaim,
    ClientSpec,
    GateDecision,
    Opportunity,
    RadarRun,
    RadarStream,
    RankedEntry,
    SkepticFinding,
)

ROOT = Path(__file__).resolve().parents[2]
RULES = Rules.load(ROOT / "tests" / "leadbed" / "rules.json")
NOW = datetime(2026, 11, 1, tzinfo=UTC)
SPEC = ClientSpec(
    id="c", name="Acme Widgets", offer="widgets for factories", markets=["GB", "FR"], sensors={},
    buyer_roles=["factories"],
)  # fmt: skip


def entry(
    name: str = "Bolt Works Ltd",
    country: str | None = "GB",
    *,
    reason: str = "Expanding its plant, awarded a contract",
    latest: date | None = date(2026, 10, 1),
    intent: int = 2,
    fit: str | None = "stated",
    site_role: str | None = None,
    rank: int = 1,
    claims: bool = True,
) -> RankedEntry:
    claim = CandidateClaim(
        ref="C1", fingerprint="f", document_id="11111111-1111-1111-1111-111111111111",
        statement="Bolt Works is expanding", source_quote="Bolt Works is expanding its plant",
        source_name="tavily", url="https://example.com/a", available_at=NOW,
        evidence_kind="full_text", verified_by="code+llm", upgraded_from=None,
    )  # fmt: skip
    c = Candidate(
        key="k", name=name, country=country, aliases=[], roles=[], stream=RadarStream.ANNOUNCEMENT,
        streams=[RadarStream.ANNOUNCEMENT], events=[], claims=[claim] if claims else [],
        window_start=None, window_end=None, window_estimated=False, window_note="",
    )  # fmt: skip
    gate = GateDecision(
        passed=True, rejected_as=None, by="llm", reason="ok", direct_buyer=True, buyer_reason=None,
        demand_reason=None, suggested_action=None, cited_refs=[],
    )  # fmt: skip
    opp = Opportunity(
        label="approach_now", play="project", intent=intent, fit=2, confidence=1, latest=latest,
        why_now=reason, words="w",
    )  # fmt: skip
    return RankedEntry(
        rank=rank, candidate=c, gate=gate,
        skeptic=SkepticFinding(stance="unknown", against=[], open_questions=[]),
        strength="medium", rank_reasons=[], fit_level=fit, site_role=site_role, opportunity=opp,
    )  # fmt: skip


def run_of(*entries: RankedEntry) -> RadarRun:
    return RadarRun(
        client_id="c", offer=SPEC.offer, as_of=NOW, queries={}, documents_by_kind={}, leads=0,
        upgraded=[], entries=list(entries), rejected=[], llm_calls=0, cost_usd=0, notes=[],
    )  # fmt: skip


def test_a_good_lead_gets_full_rule_points() -> None:
    points, cap, reasons = rule_points(entry(), SPEC, RULES, NOW)
    assert (points, cap, reasons) == (5, 5, [])


def test_junk_kinds_are_hard_fails_capped_at_one() -> None:
    names = {
        "Office for National Statistics": "statistics_body",
        "Hartley Capital Bank": "lender",
        "Water Services Regulator": "regulator",
        "British Widget Association": "trade_association",
        "Trade Weekly News": "news_site",
        "French government": "generic_government",
        "(no company named)": "no_company_named",
    }
    for name, why in names.items():
        points, cap, reasons = rule_points(entry(name), SPEC, RULES, NOW)
        assert (points, cap, reasons) == (0, 1, [why]), name


def test_a_maker_of_the_same_product_and_the_client_itself_are_hard_fails() -> None:
    assert rule_points(entry(site_role="makes"), SPEC, RULES, NOW)[2] == ["competitor"]
    assert rule_points(entry("Acme Widgets Ltd"), SPEC, RULES, NOW)[2] == ["is_the_client"]


def test_market_checks() -> None:
    assert rule_points(entry(country="US"), SPEC, RULES, NOW)[1:] == (2, ["wrong_market"])
    _, cap, reasons = rule_points(entry(country=None), SPEC, RULES, NOW)
    assert cap == 3 and reasons == ["market_unknown"]


def test_a_lead_without_a_sourced_reason_now_is_capped() -> None:
    _, cap, reasons = rule_points(entry(reason="", intent=0), SPEC, RULES, NOW)
    assert cap == 3 and "no_sourced_reason_now" in reasons
    _, cap, reasons = rule_points(entry(claims=False), SPEC, RULES, NOW)
    assert cap == 3 and "no_sourced_reason_now" in reasons


def test_a_stale_or_undated_signal_earns_no_freshness_point() -> None:
    assert rule_points(entry(latest=date(2024, 1, 1)), SPEC, RULES, NOW)[2] == ["stale"]
    assert rule_points(entry(latest=None), SPEC, RULES, NOW)[2] == ["undated"]


async def test_the_judge_score_is_held_down_by_the_rules() -> None:
    calls: list[str] = []

    async def judge(spec: Any, facts: dict[str, str]) -> JudgeOutput:
        calls.append(facts["candidate_name"])
        return JudgeOutput(reasoning="r", score=5, verdict="good")

    run = run_of(entry(rank=1), entry("Hartley Capital Bank", rank=2), entry(country=None, rank=3))
    scores = await score_run(run, SPEC, RULES, judge=judge)
    assert [s.score for s in scores] == [5, 1, 3]
    assert scores[1].junk_reason == "lender"
    assert len(calls) == 2  # a hard fail is never sent to the judge


async def test_a_low_judge_score_is_junk_with_the_judges_reason() -> None:
    async def judge(spec: Any, facts: dict[str, str]) -> JudgeOutput:
        return JudgeOutput(reasoning="r", score=1, verdict="not_a_buyer")

    (s,) = await score_run(run_of(entry()), SPEC, RULES, judge=judge)
    assert s.score == 1 and s.junk_reason == "not_a_buyer"


async def test_without_a_judge_the_score_is_the_rule_points() -> None:
    (s,) = await score_run(run_of(entry()), SPEC, RULES)
    assert s.score == 5 and s.judge_score is None and s.junk_reason is None


async def test_judge_answers_are_cached_and_reused(tmp_path: Path) -> None:
    calls = 0

    async def judge(spec: Any, facts: dict[str, str]) -> JudgeOutput:
        nonlocal calls
        calls += 1
        return JudgeOutput(reasoning="r", score=4, verdict="good")

    path = tmp_path / "cache.json"
    run = run_of(entry())
    first = JudgeCache(path)
    await score_run(run, SPEC, RULES, judge=judge, cache=first)
    first.save()
    assert json.loads(path.read_text(encoding="utf-8"))  # written by the first scoring
    (s,) = await score_run(run, SPEC, RULES, judge=judge, cache=JudgeCache(path))
    assert s.score == 4 and calls == 1


def test_the_cache_key_changes_with_the_lead_the_offer_and_the_prompt() -> None:
    facts = lead_facts(entry())
    base = cache_key(SPEC, facts, "p.v1")
    assert base == cache_key(SPEC, dict(facts), "p.v1")
    assert base != cache_key(SPEC, facts, "p.v2")
    assert base != cache_key(SPEC, {**facts, "why_now": "other"}, "p.v1")
    assert base != cache_key(SPEC.model_copy(update={"offer": "gears"}), facts, "p.v1")


async def test_summary_counts_mean_share_and_junk_by_reason() -> None:
    async def judge(spec: Any, facts: dict[str, str]) -> JudgeOutput:
        return JudgeOutput(reasoning="r", score=4, verdict="good")

    run = run_of(entry(rank=1), entry("Trade Weekly News", rank=2), entry("Hartley Bank", rank=3))
    s = summarise(await score_run(run, SPEC, RULES, judge=judge))
    assert s.leads == 3
    assert s.mean == (4 + 1 + 1) / 3
    assert s.share_call == 1 / 3
    assert s.junk == {"news_site": 1, "lender": 1}
    assert summarise([]).mean is None


async def test_the_rubric_is_zero_one_or_two() -> None:
    old = date(2026, 1, 1)  # more than 180 days before NOW
    no_proof = entry(fit=None, rank=5)
    no_proof.gate = no_proof.gate.model_copy(update={"direct_buyer": False})
    run = run_of(
        entry(rank=1),  # fresh, in market, proven: call today
        entry(latest=old, rank=2),  # proven but the reason is old: worth a look
        entry(country=None, rank=3),  # market unknown: would not call
        entry("Hartley Capital Bank", rank=4),  # not a buyer: would not call
        no_proof,  # no proof it deals in the category: would not call
    )
    scores = await score_run(run, SPEC, RULES)
    assert [s.rubric for s in scores] == [2, 1, 0, 0, 0]


async def test_harness_counts_scores_file_and_targets(tmp_path: Path) -> None:
    from northvaine.eval.leadbed import harness_of, harness_table, passes_targets, scores_payload

    run = run_of(*[entry(rank=i) for i in range(1, 5)], entry(country=None, rank=5))
    scores = await score_run(run, SPEC, RULES)
    h = harness_of(scores)
    assert (h.shown, h.good, h.strong, h.embarrassing) == (5, 4, 4, 1)
    assert not passes_targets(h)  # one embarrassing lead fails the target
    payload = scores_payload(scores)
    assert payload == {"1": 2, "2": 2, "3": 2, "4": 2, "5": 0, "notes": ""}
    (tmp_path / "c_2026-11-13.json").write_text(json.dumps(payload), encoding="utf-8")
    baseline = {"c": {"shown": 5, "strong": 1, "look": 1, "embarrassing": 3}}
    assert "| c | 5 | 4 | 4 | 1 | 2/5 | 3 | fail |" in harness_table(tmp_path, baseline)
