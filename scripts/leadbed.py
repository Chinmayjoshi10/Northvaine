"""The lead test bed: would a salesperson call this lead? (docs/EVALUATION.md, "Lead test bed").

Scores the leads of 8 varied businesses (`tests/leadbed/businesses.json`, their onboarding inputs
in `tests/leadbed/clients/`) with code rules plus a model judge, and prints mean score, share of
leads scored 4 or more, and the junk leads by reason, per business and overall.

Where each run comes from, per business:
  1. a recording in `reports/leadbed/recordings/<id>/`: replayed with the current code, free;
  2. else a saved run in `reports/leadbed/runs/<id>.json`: scored as it is;
  3. else nothing: say so. `--live --yes` records the missing ones (spends Tavily credits and
     model money, held to `--max-tavily` and `--max-usd`).

Reports name real companies, so they go under `reports/leadbed/` (never committed).

  uv run python scripts/tasks.py leadbed -- --replay            (free; the default)
  uv run python scripts/tasks.py leadbed -- --live --yes        (records what is missing)
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import sys
from dataclasses import asdict
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import ModuleType
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from northvaine.core.settings import Settings, get_settings  # noqa: E402
from northvaine.eval.leadbed import (  # noqa: E402
    CALL_SCORE,
    TARGET_MEAN,
    Harness,
    JudgeCache,
    LeadScore,
    Rules,
    Summary,
    harness_dir,
    harness_of,
    harness_table,
    make_llm_judge,
    score_run,
    scores_payload,
    summarise,
    top_n,
)
from northvaine.radar.models import ClientSpec, RadarRun, load_client_spec  # noqa: E402

BED = ROOT / "tests" / "leadbed"  # rules.json, baseline.json: no company data
OUT = ROOT / "reports" / "leadbed"  # the detail report, with lead names (never committed)
MIN_USD_LEFT = Decimal("0.05")
SHOWN = 5  # the Station shows five leads; the 0/1/2 rubric is applied to them


def load_radar() -> ModuleType:
    spec = importlib.util.spec_from_file_location("nv_leadbed_radar", ROOT / "scripts" / "radar.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def tavily_credits(recording: Any) -> int:
    """Credits a recording spent: what each Tavily answer reports, else one per call."""
    total = 0
    for ex in recording.exchanges:
        if "tavily" not in ex.url:
            continue
        body = ex.body_json if isinstance(ex.body_json, dict) else {}
        total += int((body.get("usage") or {}).get("credits", 1))
    return total


def fmt(value: float | None, pct: bool = False) -> str:
    if value is None:
        return "-"
    return f"{value:.0%}" if pct else f"{value:.2f}"


def junk_text(summary: Summary) -> str:
    return ", ".join(f"{k} {n}" for k, n in summary.junk.items()) or "none"


def render(
    rows: list[tuple[str, str, Summary]], overall: Summary, spent: dict[str, Any], when: str
) -> str:
    out = [
        f"# Lead test bed ({when})",
        "",
        f'A lead scores 0-5 on "would a salesperson call this?". Target: mean at least '
        f"{TARGET_MEAN:.0f}; a call is a score of {CALL_SCORE} or more; junk is below 3.",
        "",
        "| Business | Source | Leads | Mean | Share >= 4 | Junk by reason |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for name, source, s in rows:
        out.append(
            f"| {name} | {source} | {s.leads} | {fmt(s.mean)} | {fmt(s.share_call, True)} "
            f"| {junk_text(s)} |"
        )
    out.append(
        f"| **All** | | {overall.leads} | {fmt(overall.mean)} | {fmt(overall.share_call, True)} "
        f"| {junk_text(overall)} |"
    )
    out += ["", f"Spend this session: {json.dumps(spent)}"]
    return "\n".join(out) + "\n"


def detail(scores: list[LeadScore]) -> str:
    out = [
        "| Rank | Lead | Country | Score | Rules | Judge | Why |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for s in scores:
        why = s.junk_reason or ", ".join(s.reasons) or "good"
        out.append(
            f"| {s.rank} | {s.name} | {s.country or '-'} | {s.score} | {s.rule_points} "
            f"| {s.judge_score if s.judge_score is not None else '-'} | {why} |"
        )
    return "\n".join(out)


async def obtain_run(
    business: str,
    spec: ClientSpec,
    radar: ModuleType,
    out: Path,
    harness: Path,
    *,
    live: bool,
    yes: bool,
    credits_left: int,
    usd_left: Decimal,
    settings: Settings,
) -> tuple[RadarRun | None, str, int, Decimal]:
    """(run, source, tavily credits used, model dollars used) for one business."""
    folder = harness / "recordings" / business
    saved = harness / "runs" / f"{business}.json"
    used_credits, used_usd = 0, Decimal("0")
    have = all((folder / name).is_file() for name in radar.FILES)
    if not have and live:
        if not yes:
            radar.print_plan(spec, datetime.now(UTC), settings)
            return None, "needs --yes to record", 0, Decimal("0")
        if credits_left < settings.tavily_max_calls_per_run or usd_left < MIN_USD_LEFT:
            return None, "skipped: spend cap", 0, Decimal("0")
        code = await asyncio.to_thread(  # radar.main runs its own event loop
            radar.main,
            [
                "--client", business, "--record", "--yes",
                "--clients-dir", str(harness / "specs"),
                "--fixtures-dir", str(harness / "recordings"),
                "--out", str(out / "radar"),
            ]
        )  # fmt: skip
        have = code == 0 and all((folder / name).is_file() for name in radar.FILES)
        if not have:
            return None, "record failed", 0, Decimal("0")
        recording = radar.load_replay(folder, business)
        used_credits = tavily_credits(recording)
    if have:
        recording = radar.load_replay(folder, business)
        try:
            run = await radar.run_replay(spec, recording)
        except radar.Refused as refusal:
            return None, f"recording refused: {refusal}", used_credits, used_usd
        saved.parent.mkdir(parents=True, exist_ok=True)
        saved.write_text(run.model_dump_json(indent=1), encoding="utf-8")
        used_usd = Decimal(str(run.cost_usd))
        return run, "replayed (live)" if used_credits else "replayed", used_credits, used_usd
    if saved.is_file():
        run = RadarRun.model_validate_json(saved.read_text(encoding="utf-8"))
        return run, "saved run", 0, Decimal("0")
    return None, "no recording (use --live --yes)", 0, Decimal("0")


async def amain(args: argparse.Namespace) -> int:
    radar = load_radar()
    out = Path(args.out)
    rules = Rules.load(BED / "rules.json")
    harness = harness_dir(ROOT)
    manifest = [
        {"id": p.stem}
        for p in sorted((harness / "specs").glob("*.json"))
        if not args.business or p.stem in args.business
    ]
    settings = get_settings() if (args.live or not args.no_judge) else Settings(_env_file=None)
    judge, judge_spent = None, (lambda: Decimal("0"))
    if not args.no_judge:
        if settings.model_mid:
            judge, judge_spent = make_llm_judge(budget_usd=Decimal(str(args.max_usd)))
        else:
            print("MODEL_MID is not set: scoring with rules only", file=sys.stderr)
    cache = JudgeCache(out / "judge_cache.json")
    credits_left, usd_left = args.max_tavily, Decimal(str(args.max_usd))
    credits_used, run_usd = 0, Decimal("0")
    rows: list[tuple[str, str, Summary]] = []
    all_scores: list[LeadScore] = []
    details: dict[str, list[LeadScore]] = {}
    harness_rows: dict[str, Harness] = {}
    for b in manifest:
        spec = load_client_spec(b["id"], harness / "specs")
        run, source, c, u = await obtain_run(
            b["id"], spec, radar, out, harness,
            live=args.live, yes=args.yes, credits_left=credits_left, usd_left=usd_left,
            settings=settings,
        )  # fmt: skip
        credits_left -= c
        usd_left -= u
        credits_used += c
        run_usd += u
        if run is None:
            print(f"{b['id']}: {source}")
            rows.append((b["id"], source, summarise([])))
            continue
        scores = await score_run(run, spec, rules, judge=judge, cache=cache)
        cache.save()
        details[b["id"]] = scores
        shown = top_n(scores, SHOWN)  # the rubric is applied to what the Station shows
        harness_rows[b["id"]] = harness_of(shown)
        day = datetime.now(UTC).strftime("%Y-%m-%d")
        (harness / "scores").mkdir(parents=True, exist_ok=True)
        (harness / "scores" / f"{b['id']}_{day}.json").write_text(
            json.dumps(scores_payload(shown, "auto: rules + judge pre-score"), indent=1),
            encoding="utf-8",
        )
        all_scores += scores
        rows.append((b["id"], source, summarise(scores)))
        if judge is not None and judge_spent() + run_usd > Decimal(str(args.max_usd)):
            print("model spend cap reached: stopping", file=sys.stderr)
            break
    overall = summarise(all_scores)
    spent = {
        "tavily_credits": credits_used,
        "nebius_usd_recording": float(run_usd),
        "nebius_usd_judge": float(judge_spent()),
    }
    when = datetime.now(UTC).strftime("%Y-%m-%d")
    folder = out / when
    folder.mkdir(parents=True, exist_ok=True)
    text = render(rows, overall, spent, when)
    text += "\n" + harness_table(
        harness / "scores", json.loads((BED / "baseline.json").read_text())
    )
    text += "\n"
    (folder / "leadbed.md").write_text(
        text + "\n\n" + "\n\n".join(f"## {k}\n\n{detail(v)}" for k, v in details.items()) + "\n",
        encoding="utf-8",
    )
    (folder / "leadbed.json").write_text(
        json.dumps(
            {
                "overall": asdict(overall),
                "businesses": {k: [asdict(s) for s in v] for k, v in details.items()},
                "spent": spent,
            },
            indent=1,
        ),
        encoding="utf-8",
    )
    print(text)
    print(f"wrote {folder / 'leadbed.md'}")
    return 0


def _use_test_database() -> None:
    """A live run writes its model-call ledger to the test database, never the main one."""
    import os

    from dotenv import dotenv_values

    test_url = os.environ.get("TEST_DATABASE_URL") or dotenv_values(ROOT / ".env").get(
        "TEST_DATABASE_URL"
    )
    if test_url:
        os.environ["DATABASE_URL"] = test_url
    # the quick profile of a first radar (D130): the same settings a visitor's run uses
    from northvaine.api.onboarding import QUICK_PROFILE

    for name, value in QUICK_PROFILE.items():
        os.environ.setdefault(name.upper(), str(value))


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="leadbed.py", description=__doc__.splitlines()[0])
    p.add_argument(
        "--replay", action="store_true", help="free: replay recordings, score saved runs"
    )
    p.add_argument("--live", action="store_true", help="record missing runs live (SPENDS MONEY)")
    p.add_argument("--yes", action="store_true", help="with --live: actually call the APIs")
    p.add_argument("--business", action="append", help="only this business id (repeatable)")
    p.add_argument("--no-judge", action="store_true", help="rules only, no model calls")
    p.add_argument("--out", default=str(OUT), help="reports folder (default reports/leadbed)")
    p.add_argument("--max-tavily", type=int, default=300, help="Tavily credit cap for --live")
    p.add_argument("--max-usd", type=float, default=4.0, help="model spend cap (recording + judge)")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.live and args.replay:
        print("--live and --replay exclude each other", file=sys.stderr)
        return 2
    if args.yes and not args.live:
        print("--yes only applies to --live", file=sys.stderr)
        return 2
    if args.live:
        _use_test_database()
    return asyncio.run(amain(args))


if __name__ == "__main__":
    sys.exit(main())
