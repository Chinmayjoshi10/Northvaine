"""The lead test bed scorer: "would a salesperson call this lead?" (docs/EVALUATION.md).

Every lead a run shows (a brief entry) gets a score from 0 to 5 from two checks:

1. Rules, in code: is it a real organisation of a kind that buys (not a statistics body, lender,
   regulator, trade association, news site, general government, or the client itself or a maker of
   its product), is it in a target market, is there a sourced reason to call now, and is there
   evidence it deals in what the client sells. The word lists are data (`tests/leadbed/rules.json`).
2. A model judge (`judge_lead`, through `brain/llm.py`, CLAUDE.md #8), told the same question a
   salesperson asks. Its answers are cached on disk, so scoring the same leads twice costs nothing
   and gives the same number.

The final score is the judge's, held down by the rules: a hard fail caps it at 1, an unknown
market or no sourced reason to call now caps it at 3. Without a judge the score is the rules'
own points. Per business and overall the report gives the mean score, the share of leads scored
4 or more, and the count of junk leads (score below 3) by reason.

Nothing here knows an industry: the client's own spec supplies offer, markets and buyer roles.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

from pydantic import Field

from northvaine.core.models import NorthvaineModel
from northvaine.radar.models import ClientSpec, RadarRun, RankedEntry

TARGET_MEAN = 4.0  # the bar a lead-quality change must beat
CALL_SCORE = 4  # a lead at or above this is one a salesperson would call
JUNK_BELOW = 3  # a lead below this is junk and is counted by reason
NOT_A_COMPANY_OR_RIVAL = {"competitor", "is_the_client", "no_company_named"}  # scored 0

Verdict = Literal[
    "good", "not_a_buyer", "competitor", "wrong_market", "no_reason_now", "stale", "too_vague"
]


class JudgeOutput(NorthvaineModel):
    reasoning: str = ""
    score: int = Field(ge=0, le=5)
    verdict: Verdict = "too_vague"


@dataclass(frozen=True)
class Rules:
    junk_name_patterns: dict[str, list[re.Pattern[str]]]
    stale_days: int = 400
    why_now_min_intent: int = 1

    @classmethod
    def load(cls, path: Path) -> Rules:
        raw = json.loads(path.read_text(encoding="utf-8"))
        patterns = {
            reason: [re.compile(p, re.IGNORECASE) for p in words]
            for reason, words in raw["junk_name_patterns"].items()
        }
        return cls(
            junk_name_patterns=patterns,
            stale_days=int(raw.get("stale_days", 400)),
            why_now_min_intent=int(raw.get("why_now_min_intent", 1)),
        )


@dataclass
class LeadScore:
    """One lead, scored. `reasons` are the rule findings; `junk_reason` is set when score < 3."""

    business: str
    rank: int
    name: str
    country: str | None
    rule_points: int
    cap: int
    judge_score: int | None
    judge_verdict: str | None
    judge_reasoning: str
    score: int
    reasons: list[str] = field(default_factory=list)
    junk_reason: str | None = None
    rubric: int = 0  # the plan's 0 / 1 / 2: would not call / worth a look / call today


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) >= 4}


def hard_fail(entry: RankedEntry, spec: ClientSpec, rules: Rules) -> str | None:
    """The first reason this lead can never be a call, or None."""
    c = entry.candidate
    name = c.name.strip()
    for reason, patterns in rules.junk_name_patterns.items():
        if any(p.search(name) for p in patterns):
            return reason
    if entry.site_role == "makes":
        return "competitor"
    own = _words(spec.name or "")
    if own and own <= _words(name):
        return "is_the_client"
    return None


def rule_points(
    entry: RankedEntry, spec: ClientSpec, rules: Rules, as_of: datetime
) -> tuple[int, int, list[str]]:
    """(points 0-5, score cap, findings). Points: market 1, sourced reason now 1-2, buyer
    evidence 0-2. A hard fail is 0 points with a cap of 1."""
    c = entry.candidate
    reasons: list[str] = []
    cap = 5
    failed = hard_fail(entry, spec, rules)
    if failed:
        return 0, 1, [failed]
    points = 0
    if c.country and c.country in spec.markets:
        points += 1
    elif c.country is None:
        reasons.append("market_unknown")
        cap = min(cap, 3)
    else:
        reasons.append("wrong_market")
        cap = min(cap, 2)
    opp = entry.opportunity
    sourced = bool(c.claims) and all(cl.url for cl in c.claims)
    has_reason = bool(opp and opp.why_now.strip() and opp.intent >= rules.why_now_min_intent)
    if has_reason and sourced:
        points += 1
        latest = opp.latest if opp else None
        if latest is not None and (as_of.date() - latest) <= timedelta(days=rules.stale_days):
            points += 1
        else:
            reasons.append("stale" if latest is not None else "undated")
    else:
        reasons.append("no_sourced_reason_now")
        cap = min(cap, 3)
    if entry.fit_level == "stated" or entry.requirement == "stated":
        points += 2
    elif (
        entry.fit_level == "related"
        or entry.requirement == "related"
        or entry.gate.direct_buyer
        or entry.site_role == "uses"
    ):
        points += 1
    else:
        reasons.append("weak_buyer_evidence")
    return min(points, 5), cap, reasons


def lead_facts(entry: RankedEntry) -> dict[str, str]:
    """What the judge sees: the lead's checked facts, nothing the tool inferred beyond its notes."""
    c = entry.candidate
    claims = "\n".join(f'{cl.statement} / "{cl.source_quote}" ({cl.url})' for cl in c.claims[:6])
    return {
        "candidate_name": c.name,
        "country": c.country or "unknown",
        "claims": claims or "none",
        "why_now": entry.opportunity.why_now if entry.opportunity else "",
        "gate_reason": entry.gate.reason or "",
    }


Judge = Callable[[ClientSpec, dict[str, str]], Awaitable[JudgeOutput]]


def cache_key(spec: ClientSpec, facts: dict[str, str], prompt_label: str) -> str:
    payload = json.dumps(
        {
            "prompt": prompt_label,
            "offer": spec.offer,
            "roles": spec.buyer_roles,
            "notb": spec.not_buyers,
            "markets": spec.markets,
            "facts": facts,
        },
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


class JudgeCache:
    """A JSON file of judge answers by input hash, so the same lead is judged once."""

    def __init__(self, path: Path | None) -> None:
        self.path = path
        self.data: dict[str, Any] = {}
        if path is not None and path.is_file():
            self.data = json.loads(path.read_text(encoding="utf-8"))

    def get(self, key: str) -> JudgeOutput | None:
        raw = self.data.get(key)
        return JudgeOutput.model_validate(raw) if raw else None

    def put(self, key: str, value: JudgeOutput) -> None:
        self.data[key] = value.model_dump()

    def save(self) -> None:
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self.data, indent=1), encoding="utf-8")


def make_llm_judge(*, budget_usd: Decimal) -> tuple[Judge, Callable[[], Decimal]]:
    """A judge that calls the model through `brain/llm.py`; returns it and a spend reader."""
    from northvaine.brain.budget import RunContext
    from northvaine.brain.fencing import Untrusted
    from northvaine.brain.llm import complete_json
    from northvaine.brain.prompts import load_prompt
    from northvaine.core.models import ModelTier

    run = RunContext(budget_usd=budget_usd)
    prompt = load_prompt("leadbed_judge")

    async def judge(spec: ClientSpec, facts: dict[str, str]) -> JudgeOutput:
        result = await complete_json(
            tier=ModelTier.MID,
            prompt=prompt,
            variables={
                "offer": spec.offer,
                "buyer_roles": "; ".join(spec.buyer_roles) or "not stated",
                "not_buyers": "; ".join(spec.not_buyers) or "not stated",
                "markets": ", ".join(spec.markets) or "not stated",
                "candidate_name": Untrusted(facts["candidate_name"]),
                "country": facts["country"],
                "claims": Untrusted(facts["claims"]),
                "why_now": Untrusted(facts["why_now"]),
                "gate_reason": Untrusted(facts["gate_reason"]),
            },
            output_model=JudgeOutput,
            purpose="leadbed_judge",
            run=run,
            max_tokens=400,
        )
        return result.value

    return judge, lambda: run.spent


async def score_run(
    run: RadarRun,
    spec: ClientSpec,
    rules: Rules,
    *,
    judge: Judge | None = None,
    cache: JudgeCache | None = None,
    prompt_label: str = "leadbed_judge.v1",
) -> list[LeadScore]:
    """Score every lead the run shows."""
    out: list[LeadScore] = []
    for entry in run.entries:
        points, cap, reasons = rule_points(entry, spec, rules, run.as_of)
        verdict: str | None = None
        reasoning = ""
        judged: int | None = None
        if judge is not None and cap > 1:  # a hard fail needs no judge
            facts = lead_facts(entry)
            key = cache_key(spec, facts, prompt_label)
            answer = cache.get(key) if cache else None
            if answer is None:
                answer = await judge(spec, facts)
                if cache:
                    cache.put(key, answer)
            judged, verdict, reasoning = answer.score, answer.verdict, answer.reasoning
        base = judged if judged is not None else points
        score = min(base, cap)
        if cap == 1 and reasons:  # a hard fail: 0 for a rival or no company, else 1
            score = 0 if reasons[0] in NOT_A_COMPANY_OR_RIVAL else 1
        junk = None
        if score < JUNK_BELOW:
            if cap == 1 and reasons:
                junk = reasons[0]  # a hard fail
            elif verdict and verdict != "good":
                junk = verdict
            else:
                junk = reasons[0] if reasons else "other"
        out.append(
            LeadScore(
                rubric=rubric_of(entry, run.as_of, reasons, cap, judged),
                business=run.client_id,
                rank=entry.rank,
                name=entry.candidate.name,
                country=entry.candidate.country,
                rule_points=points,
                cap=cap,
                judge_score=judged,
                judge_verdict=verdict,
                judge_reasoning=reasoning,
                score=score,
                reasons=reasons,
                junk_reason=junk,
            )
        )
    return out


FRESH_DAYS = 180  # a dated reason this recent makes a lead "call today"
ZERO_REASONS = {"market_unknown", "wrong_market", "weak_buyer_evidence"}


def rubric_of(
    entry: RankedEntry,
    as_of: datetime,
    reasons: list[str],
    cap: int,
    judged: int | None,
) -> int:
    """The plan's rubric (Plan B 6.2). 0: not a company or a seller, market unknown or outside,
    no proof it deals in the category, or the judge would not call. 2: none of those and a dated
    reason within 180 days (and the judge, when there is one, says call). 1: the rest."""
    if cap == 1 or ZERO_REASONS & set(reasons) or (judged is not None and judged < JUNK_BELOW):
        return 0
    latest = entry.opportunity.latest if entry.opportunity else None
    fresh = latest is not None and (as_of.date() - latest) <= timedelta(days=FRESH_DAYS)
    if (
        fresh
        and (judged is None or judged >= CALL_SCORE)
        and "no_sourced_reason_now" not in reasons
    ):
        return 2
    return 1


@dataclass
class Harness:
    shown: int
    good: int  # rubric >= 1
    strong: int  # rubric == 2
    embarrassing: int  # rubric == 0


def harness_of(scores: list[LeadScore]) -> Harness:
    return Harness(
        shown=len(scores),
        good=sum(1 for s in scores if s.rubric >= 1),
        strong=sum(1 for s in scores if s.rubric == 2),
        embarrassing=sum(1 for s in scores if s.rubric == 0),
    )


def scores_payload(scores: list[LeadScore], notes: str = "") -> dict[str, Any]:
    """The scores file: {"<rank>": rubric, ..., "notes": ""} (Plan B 6.2)."""
    return {**{str(s.rank): s.rubric for s in scores}, "notes": notes}


def passes_targets(h: Harness) -> bool:
    """Good at least 4 of 5 when 5 are shown, and nothing embarrassing."""
    return h.embarrassing == 0 and (h.shown < 5 or h.good >= 4)


@dataclass
class Summary:
    leads: int
    mean: float | None
    share_call: float | None  # share of leads scored >= CALL_SCORE
    junk: dict[str, int]


def summarise(scores: list[LeadScore]) -> Summary:
    if not scores:
        return Summary(0, None, None, {})
    junk = Counter(s.junk_reason for s in scores if s.junk_reason)
    return Summary(
        leads=len(scores),
        mean=sum(s.score for s in scores) / len(scores),
        share_call=sum(1 for s in scores if s.score >= CALL_SCORE) / len(scores),
        junk=dict(junk.most_common()),
    )


def top_n(scores: list[LeadScore], n: int) -> list[LeadScore]:
    """The first n leads by brief rank: what a salesperson reads first."""
    return sorted(scores, key=lambda s: s.rank)[:n]


def shown_scores(run: RadarRun, scores: list[LeadScore], n: int) -> list[LeadScore]:
    """The leads the Station lists, first n by rank: an entry the evidence floor or the review
    held back is never shown (D148), so it is never scored as shown."""
    held = {e.rank for e in run.entries if e.opportunity is not None and e.opportunity.held}
    return top_n([s for s in scores if s.rank not in held], n)


def latest_score_files(scores_dir: Path) -> dict[str, Path]:
    """business id -> its newest `<id>_<date>.json` scores file."""
    found: dict[str, Path] = {}
    for path in sorted(scores_dir.glob("*_*.json")):
        found[path.stem.rsplit("_", 1)[0]] = path  # sorted by date, so the last one wins
    return found


def harness_table(scores_dir: Path, baseline: dict[str, Any]) -> str:
    """The harness table: this run's good / strong / embarrassing next to the staging baseline."""
    files = latest_score_files(scores_dir)
    lines = [
        "| Business | Shown | Good | Strong | Embarrassing | Baseline good/shown | Baseline emb. "
        "| Targets |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    ids = [k for k in baseline if not k.startswith("_")]
    totals = Harness(0, 0, 0, 0)
    for biz in ids:
        base = baseline[biz]
        base_good = f"{base['strong'] + base['look']}/{base['shown']}"
        if biz not in files:
            lines.append(
                f"| {biz} | - | - | - | - | {base_good} | {base['embarrassing']} | no scores |"
            )
            continue
        raw = json.loads(files[biz].read_text(encoding="utf-8"))
        ranks = [v for k, v in raw.items() if k != "notes"]
        h = Harness(
            len(ranks),
            sum(1 for v in ranks if v >= 1),
            sum(1 for v in ranks if v == 2),
            sum(1 for v in ranks if v == 0),
        )
        totals = Harness(
            totals.shown + h.shown,
            totals.good + h.good,
            totals.strong + h.strong,
            totals.embarrassing + h.embarrassing,
        )
        verdict = "pass" if passes_targets(h) else "fail"
        lines.append(
            f"| {biz} | {h.shown} | {h.good} | {h.strong} | {h.embarrassing} | {base_good} "
            f"| {base['embarrassing']} | {verdict} |"
        )
    base_shown = sum(baseline[b]["shown"] for b in ids)
    base_good_total = sum(baseline[b]["strong"] + baseline[b]["look"] for b in ids)
    lines.append(
        f"| **All** | {totals.shown} | {totals.good} | {totals.strong} | {totals.embarrassing} "
        f"| {base_good_total}/{base_shown} | {sum(baseline[b]['embarrassing'] for b in ids)} | |"
    )
    return "\n".join(lines)


def harness_dir(root: Path) -> Path:
    """The private harness folder: NV_HARNESS_DIR, else `.refs/audits/harness` of the main
    checkout (a worktree has no `.refs` of its own)."""
    import os
    import subprocess

    if os.environ.get("NV_HARNESS_DIR"):
        return Path(os.environ["NV_HARNESS_DIR"])
    common = subprocess.run(
        ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
        capture_output=True,
        text=True,
        cwd=root,
        check=True,
    ).stdout.strip()
    return Path(common).parent / ".refs" / "audits" / "harness"
