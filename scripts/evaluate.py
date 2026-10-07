"""Evaluate the product from filled-in scorecards (docs/EVALUATION.md).

Reads the latest `scorecard.md` per client under the reports folder, computes quality and
outcome metrics, prints a table and writes `eval.md` and `eval.json` to `reports/eval/<date>/`.
Reports name real companies, so they live under `reports/`, which is never committed (D66).
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from northvaine.eval.scorecard import Metrics, metrics, parse_scorecard  # noqa: E402


def latest_scorecards(reports: Path) -> dict[str, Path]:
    """client id -> its most recent scorecard (folders are named by run date)."""
    found: dict[str, Path] = {}
    for path in sorted(reports.glob("*/*/scorecard.md")):
        found[path.parent.parent.name] = path  # sorted, so the last date wins
    return found


def _pct(value: float | None) -> str:
    return "-" if value is None else f"{value:.0%}"


def render(rows: list[Metrics], when: str) -> str:
    out = [
        f"# Northvaine evaluation ({when})",
        "",
        "## Quality (founder ratings)",
        "",
        "| Client | Rated | Correct | Relevant | New/worth acting | Actionable | All four "
        "| Wrong rejections | Quality gate |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for m in rows:
        gate = {True: "pass", False: "fail", None: "not rated"}[m.passes_quality_gate]
        out.append(
            f"| {m.client} | {m.rated} | {_pct(m.correct_rate)} | {_pct(m.relevant_rate)} | "
            f"{_pct(m.new_rate)} | {_pct(m.actionable_rate)} | {m.all_four} | "
            f"{_pct(m.wrong_rejection_rate)} | {gate} |"
        )
    out += [
        "",
        "## Outcomes (after contact)",
        "",
        "| Client | Delivered | Already known | New intelligence | Acted on | Response "
        "| Positive |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for m in rows:
        out.append(
            f"| {m.client} | {m.delivered} | {_pct(m.known_rate)} | "
            f"{_pct(m.new_intelligence_rate)} | {_pct(m.acted_on_rate)} | "
            f"{_pct(m.response_rate)} | {_pct(m.positive_rate)} |"
        )
    out += ["", "## Notes", ""]
    for m in rows:
        for note in m.notes:
            out.append(f"- {m.client}: {note}")
    out.append("")
    return "\n".join(out)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Evaluate radar scorecards.")
    parser.add_argument("--reports", default="reports/radar", help="folder of radar reports")
    parser.add_argument("--out", default="reports/eval", help="where eval reports are written")
    parser.add_argument("--min-all-four", type=int, default=2, help="the quality-gate threshold")
    return parser


def main(argv: list[str] | None = None, *, root: Path = ROOT) -> int:
    args = build_parser().parse_args(argv)
    reports = (root / args.reports).resolve()
    cards = latest_scorecards(reports)
    if not cards:
        print(f"no scorecards under {reports}; run `tasks.py radar` first", file=sys.stderr)
        return 2
    rows = [
        metrics(
            parse_scorecard(path.read_text(encoding="utf-8"), client=client),
            min_all_four=args.min_all_four,
        )
        for client, path in sorted(cards.items())
    ]
    when = datetime.now(UTC).date().isoformat()
    text = render(rows, when)
    folder = (root / args.out / when).resolve()
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "eval.md").write_text(text, encoding="utf-8", newline="\n")
    (folder / "eval.json").write_text(
        json.dumps([asdict(m) for m in rows], indent=2), encoding="utf-8", newline="\n"
    )
    print(text)
    print(f"wrote {folder / 'eval.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
